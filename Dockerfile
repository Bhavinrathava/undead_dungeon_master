FROM python:3.12-slim

WORKDIR /app

# Install dependencies before copying the full source so this layer is cached
COPY ai_dungeon_master/requirements.txt requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the project
COPY . .

EXPOSE 8501

CMD ["streamlit", "run", "main.py", \
     "--server.port=8501", \
     "--server.address=0.0.0.0", \
     "--server.headless=true"]
