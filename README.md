# Agent MVP (OpenAI Agents SDK + Faust/Redpanda + Flask UI)

Minimal multi-agent MVP with JSON message serialization, Codespaces support, and a Bootstrap UI.

## Quickstart

1. API key:
   ```bash
   export OPENAI_API_KEY=sk-...
   ```

2. Start Redpanda:
   ```bash
   docker run -d --name=redpanda -p 9092:9092 -p 9644:9644 redpandadata/redpanda:v24.3.18 \     redpanda start --overprovisioned --smp 1 --memory 1G --reserve-memory 0M --node-id 0 --check=false \     --kafka-addr PLAINTEXT://0.0.0.0:9092 --advertise-kafka-addr PLAINTEXT://localhost:9092
   ```

3. Worker:
   ```bash
   make worker
   ```

4. UI:
   ```bash
   make web   # http://localhost:5000
   ```

5. Enqueue a task:
   ```bash
   make send
   # or: make send TEXT="Implement cursor pagination for /invoices API"
   ```
