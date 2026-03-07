"""
ui/app.py
Streamlit application — adventure selection screen and chat screen.
"""

from __future__ import annotations

import base64
import io
import wave
from pathlib import Path

import numpy as np

import streamlit as st
import streamlit.components.v1 as components

from ai_dungeon_master.adventure.loader import AdventureLoader
from ai_dungeon_master.adventure.models import Adventure
from ai_dungeon_master.agent.resolver_agent import SkillCheckOutcome
from ai_dungeon_master.session import SessionManager

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

DATA_DIR = Path(__file__).parent.parent / "data" / "adventures"

# ---------------------------------------------------------------------------
# TTS configuration
# ---------------------------------------------------------------------------

TTS_VOICE = "af_heart"  # Kokoro voice — see https://huggingface.co/hexgrad/Kokoro-82M for options


def _init_tts() -> None:
    if "tts_enabled" not in st.session_state:
        st.session_state.tts_enabled = False
    if "tts_model" not in st.session_state:
        st.session_state.tts_model = None
    if "tts_audio_data" not in st.session_state:
        st.session_state.tts_audio_data = None
    if "tts_audio_played" not in st.session_state:
        st.session_state.tts_audio_played = True
    if "tts_error" not in st.session_state:
        st.session_state.tts_error = None


def _get_tts_model():
    if st.session_state.tts_model is None:
        from kokoro import KPipeline  # lazy import — only needed when TTS is on
        with st.spinner("Loading TTS model…"):
            st.session_state.tts_model = KPipeline(lang_code="a")
    return st.session_state.tts_model


def _generate_tts(text: str) -> bytes | None:
    """Generate WAV audio for *text*; returns raw bytes or None on error."""
    try:
        pipe = _get_tts_model()
        chunks = [audio for _, _, audio in pipe(text, voice=TTS_VOICE)]
        if not chunks:
            return None
        audio = np.concatenate(chunks)
        audio_i16 = (audio * 32767).clip(-32768, 32767).astype("int16")

        buf = io.BytesIO()
        with wave.open(buf, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(24000)  # Kokoro outputs at 24 kHz
            wf.writeframes(audio_i16.tobytes())
        st.session_state.tts_error = None
        return buf.getvalue()
    except Exception as exc:
        st.session_state.tts_error = str(exc)
        return None


def _render_tts_toggle() -> None:
    """Render a TTS toggle in the sidebar."""
    is_on = st.session_state.get("tts_enabled", False)
    new_val = st.toggle("🔊 Text-to-Speech", value=is_on, key="tts_toggle")
    if new_val != is_on:
        st.session_state.tts_enabled = new_val
        if not new_val:
            st.session_state.tts_model = None
            st.session_state.tts_audio_data = None


def _render_combat_popup(world_state) -> None:
    """Render a fixed-position floating combat status panel when in combat.

    Uses a native HTML <details> element so the user can minimize/expand
    without requiring JavaScript.  Position is fixed to the bottom-right
    corner of the viewport so it overlays the chat screen.
    """
    combat = world_state.combat
    if combat is None:
        return

    # --- Party rows ---
    party_rows_html = ""
    for p in combat.party:
        hp_pct = (p.current_hp / p.max_hp * 100) if p.max_hp else 0
        bar_color = "#4ade80" if hp_pct > 50 else ("#facc15" if hp_pct > 25 else "#f87171")
        is_current = p.name == combat.current_actor
        row_bg = "background:#1e3a5f;" if is_current else ""
        conditions_html = (
            f"<span style='color:#facc15;font-size:0.7em;margin-left:4px;'>"
            f"[{', '.join(p.conditions)}]</span>"
            if p.conditions else ""
        )
        status_html = (
            f"<span style='color:#f87171;font-size:0.7em;margin-left:4px;'>"
            f"[{p.status.value.upper()}]</span>"
            if p.status.value != "alive" else ""
        )
        marker = "⚡ " if is_current else ""
        party_rows_html += (
            f"<div style='padding:4px 6px;border-radius:4px;margin-bottom:3px;{row_bg}'>"
            f"<div style='display:flex;justify-content:space-between;align-items:center;'>"
            f"<span style='font-weight:bold;'>{marker}{p.name}{status_html}{conditions_html}</span>"
            f"<span style='font-size:0.78em;color:#94a3b8;'>AC {p.ac}</span>"
            f"</div>"
            f"<div style='background:#334155;border-radius:3px;height:5px;margin-top:3px;'>"
            f"<div style='background:{bar_color};width:{min(hp_pct, 100):.0f}%;height:5px;border-radius:3px;'></div>"
            f"</div>"
            f"<div style='font-size:0.72em;color:#94a3b8;'>{p.current_hp}/{p.max_hp} HP</div>"
            f"</div>"
        )

    # --- Enemy rows ---
    enemy_rows_html = ""
    for e in combat.living_enemies:
        hp_pct = (e.current_hp / e.max_hp * 100) if e.max_hp else 0
        bar_color = "#4ade80" if hp_pct > 50 else ("#facc15" if hp_pct > 25 else "#f87171")
        is_current = e.instance_id == combat.current_actor
        row_bg = "background:#1e3a5f;" if is_current else ""
        conditions_html = (
            f"<span style='color:#facc15;font-size:0.7em;margin-left:4px;'>"
            f"[{', '.join(e.conditions)}]</span>"
            if e.conditions else ""
        )
        marker = "⚡ " if is_current else ""
        enemy_rows_html += (
            f"<div style='padding:4px 6px;border-radius:4px;margin-bottom:3px;{row_bg}'>"
            f"<div style='display:flex;justify-content:space-between;align-items:center;'>"
            f"<span style='font-weight:bold;color:#fca5a5;'>{marker}{e.name}{conditions_html}</span>"
            f"<span style='font-size:0.78em;color:#94a3b8;'>AC {e.ac}</span>"
            f"</div>"
            f"<div style='background:#334155;border-radius:3px;height:5px;margin-top:3px;'>"
            f"<div style='background:{bar_color};width:{min(hp_pct, 100):.0f}%;height:5px;border-radius:3px;'></div>"
            f"</div>"
            f"<div style='font-size:0.72em;color:#94a3b8;'>{e.current_hp}/{e.max_hp} HP</div>"
            f"</div>"
        )
    if not enemy_rows_html:
        enemy_rows_html = "<div style='color:#64748b;font-size:0.8em;padding:4px 6px;'>No living enemies</div>"

    # --- Turn order ---
    turn_parts = [
        f"<span style='{'color:#60a5fa;font-weight:bold;' if i == combat.current_turn_index else 'color:#94a3b8;'}'>{actor}</span>"
        for i, actor in enumerate(combat.turn_order)
    ]
    turn_order_html = "<span style='color:#475569;'> → </span>".join(turn_parts)

    # --- Combat log (last 5 entries) ---
    log_section = ""
    if combat.combat_log:
        log_entries = "".join(
            f"<div style='font-size:0.72em;color:#94a3b8;padding:1px 0;border-bottom:1px solid #1e293b;'>{entry}</div>"
            for entry in combat.combat_log[-5:]
        )
        log_section = (
            "<div style='font-size:0.72em;text-transform:uppercase;letter-spacing:0.05em;"
            "color:#64748b;margin:6px 0 3px;padding-bottom:2px;border-bottom:1px solid #334155;'>"
            "Recent Events</div>"
            + log_entries
        )

    html = f"""
<style>
#combat-float {{
  position: fixed;
  bottom: 20px;
  right: 20px;
  width: 270px;
  z-index: 9999;
  font-family: -apple-system, BlinkMacSystemFont, sans-serif;
  font-size: 13px;
}}
#combat-float details {{
  background: #1e293b;
  border: 1px solid #475569;
  border-radius: 8px;
  box-shadow: 0 4px 24px rgba(0,0,0,0.6);
  overflow: hidden;
}}
#combat-float summary {{
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 8px 12px;
  background: #7f1d1d;
  cursor: pointer;
  user-select: none;
  color: #fecaca;
  font-weight: 600;
  list-style: none;
  outline: none;
}}
#combat-float summary::-webkit-details-marker {{ display: none; }}
#combat-float summary::marker {{ display: none; }}
#combat-float summary:hover {{ background: #991b1b; }}
#combat-float .cbody {{
  padding: 8px;
  max-height: 480px;
  overflow-y: auto;
  color: #e2e8f0;
}}
#combat-float .cbody::-webkit-scrollbar {{ width: 4px; }}
#combat-float .cbody::-webkit-scrollbar-track {{ background: #1e293b; }}
#combat-float .cbody::-webkit-scrollbar-thumb {{ background: #475569; border-radius: 2px; }}
#combat-float .csec {{
  font-size: 0.72em;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  color: #64748b;
  margin: 6px 0 3px;
  padding-bottom: 2px;
  border-bottom: 1px solid #334155;
}}
</style>
<div id="combat-float">
  <details open>
    <summary>
      <span>⚔️ Combat — Round {combat.round_number}</span>
      <span style="font-size:0.8em;opacity:0.7;">▲ / ▼</span>
    </summary>
    <div class="cbody">
      <div style="padding:4px 6px;background:#172554;border-radius:4px;margin-bottom:6px;">
        <div style="font-size:0.72em;color:#60a5fa;margin-bottom:2px;">TURN ORDER</div>
        <div style="line-height:1.8;word-break:break-all;">{turn_order_html}</div>
      </div>
      <div class="csec">Party</div>
      {party_rows_html}
      <div class="csec">Enemies</div>
      {enemy_rows_html}
      {log_section}
    </div>
  </details>
</div>
"""
    st.markdown(html, unsafe_allow_html=True)


def _load_all_adventures() -> list[Adventure]:
    adventures: list[Adventure] = []
    for yaml_file in sorted(DATA_DIR.glob("*.yaml")):
        try:
            adventures.append(AdventureLoader.load_from_yaml(yaml_file))
        except Exception as e:
            print(f"Error loading {yaml_file} — skipping. Error: {e}")
    return adventures


def _init_state() -> None:
    if "screen" not in st.session_state:
        st.session_state.screen = "selection"
    if "selected_adventure" not in st.session_state:
        st.session_state.selected_adventure = None
    if "messages" not in st.session_state:
        st.session_state.messages = []
    if "session_manager" not in st.session_state:
        st.session_state.session_manager = None
    _init_tts()


def _start_adventure(adventure: Adventure) -> None:
    st.session_state.selected_adventure = adventure
    st.session_state.messages = []
    st.session_state.session_manager = SessionManager(adventure)
    st.session_state.screen = "chat"


def _back_to_selection() -> None:
    st.session_state.screen = "selection"
    st.session_state.selected_adventure = None
    st.session_state.messages = []
    st.session_state.session_manager = None


# ---------------------------------------------------------------------------
# Screens
# ---------------------------------------------------------------------------


def _render_selection() -> None:
    st.title("Undead Dungeon Master")
    st.caption("Choose your adventure to begin.")

    adventures = _load_all_adventures()

    if not adventures:
        st.warning("No adventure files found in `data/adventures/`.")
        return

    for adventure in adventures:
        with st.container(border=True):
            col_text, col_btn = st.columns([4, 1], vertical_alignment="center")
            with col_text:
                st.subheader(adventure.title)
                st.caption(f"*{adventure.setting}*")
                st.write(adventure.premise)
            with col_btn:
                if st.button(
                    "Begin",
                    key=f"start_{adventure.title}",
                    use_container_width=True,
                ):
                    _start_adventure(adventure)
                    st.rerun()


def _render_chat() -> None:
    adventure: Adventure = st.session_state.selected_adventure
    sm = st.session_state.session_manager

    # -- Sidebar --
    with st.sidebar:
        if st.button("← Adventures"):
            _back_to_selection()
            st.rerun()

        _render_tts_toggle()

        st.divider()
        st.subheader("Party")
        for pc in adventure.party:
            st.markdown(f"**{pc.name}**")
            st.caption(f"{pc.race} {pc.character_class} · Level {pc.level}")
            hp_pct = pc.current_hp / pc.max_hp if pc.max_hp else 0
            st.progress(hp_pct, text=f"HP: {pc.current_hp} / {pc.max_hp}")
            st.write("")

        st.divider()
        st.subheader("Location")
        current_loc = None
        if sm and sm.world_state.current_location_id:
            current_loc = adventure.get_location(sm.world_state.current_location_id)
        if current_loc is None:
            current_loc = adventure.starting_location
        if current_loc:
            st.markdown(f"**{current_loc.name}**")
            st.caption(
                current_loc.description[:120]
                + ("…" if len(current_loc.description) > 120 else "")
            )

    # -- Combat popup (fixed overlay, visible whenever combat is active) --
    if sm and sm.world_state.in_combat:
        _render_combat_popup(sm.world_state)

    # -- Main chat area --
    st.title(adventure.title)

    # Render history
    for msg in st.session_state.messages:
        role = "user" if msg["role"] == "user" else "assistant"
        with st.chat_message(role):
            st.markdown(msg["content"])

    # TTS error display — persists across reruns via session state
    if st.session_state.tts_error:
        st.warning(f"TTS error: {st.session_state.tts_error}")

    # TTS audio player — autoplays once per new DM response
    if st.session_state.tts_enabled and st.session_state.tts_audio_data:
        if not st.session_state.tts_audio_played:
            # Embed audio as a data URI in a fresh HTML element so the browser
            # always fires autoplay (st.audio reuses its DOM node across reruns,
            # which suppresses autoplay after the first message).
            b64 = base64.b64encode(st.session_state.tts_audio_data).decode()
            components.html(
                f'<audio autoplay src="data:audio/wav;base64,{b64}"></audio>',
                height=0,
            )
            st.session_state.tts_audio_played = True
        else:
            st.audio(st.session_state.tts_audio_data, format="audio/wav")

    # Input
    user_input = st.chat_input("What do you do?")
    if user_input:
        st.session_state.messages.append(
            {"role": "user", "content": user_input}
        )

        with st.spinner("The Dungeon Master deliberates…"):
            result = st.session_state.session_manager.send(user_input)

        if result.skill_check is not None:
            sc = result.skill_check
            sign = "+" if sc.modifier >= 0 else ""
            outcome_label, icon = {
                SkillCheckOutcome.FULL_REVEAL:   ("Full Reveal",   "✅"),
                SkillCheckOutcome.PARTIAL_REVEAL: ("Partial Reveal", "⚠️"),
                SkillCheckOutcome.FAILURE:        ("Failed",        "❌"),
            }[sc.outcome]
            st.toast(
                f"🎲 **{sc.skill_name}** check  \n"
                f"{sc.raw_roll} {sign}{sc.modifier} = **{sc.total}**"
                f"  vs  DC {sc.dc_full} (full) / {sc.dc_partial} (partial)  \n"
                f"{icon} {outcome_label}",
            )

        st.session_state.messages.append({"role": "dm", "content": result.dm_response})

        # Generate TTS audio for the DM response if enabled
        if st.session_state.tts_enabled:
            audio_data = _generate_tts(result.dm_response)
            if audio_data:
                st.session_state.tts_audio_data = audio_data
                st.session_state.tts_audio_played = False

        st.rerun()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def run_app() -> None:
    st.set_page_config(
        page_title="Undead Dungeon Master",
        page_icon="💀",
        layout="wide",
    )
    _init_state()

    if st.session_state.screen == "selection":
        _render_selection()
    else:
        _render_chat()
