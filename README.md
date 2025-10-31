# SoftLight_UIStateAgent

Production-grade, real-time UI state capture agent for a multi-agent AI system.

## Architecture

- **Backend**: FastAPI (async server)
- **Frontend**: Next.js (App Router)
- **Agents**: CrewAI modular sub-agents
- **Orchestration**: LangGraph DAG flows
- **Browser Automation**: Playwright
- **Context Sync**: MCP Server
- **Memory**: Upstash (optional)

## Structure

```
/frontend             → Next.js UI  
/backend              → FastAPI API server  
/agents               → Modular CrewAI agents  
/graph                → LangGraph DAG flows  
/utils                → Logging, Upstash sync, helpers  
/mcp                  → Multi-Context Prompting server  
/data/screenshots     → {app}/{task}/{step}.png  
/data/logs            → Full run logs per workflow  
/docker               → Dockerfiles and docker-compose setup  
```

## Quick Start

```bash
# Start all services
docker-compose -f docker/docker-compose.yml up

# Backend: http://localhost:8000
# Frontend: http://localhost:3000
# MCP: http://localhost:8001
```

## Development

Step-by-step implementation in progress.
