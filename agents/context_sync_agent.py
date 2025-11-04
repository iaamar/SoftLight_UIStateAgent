from crewai import Agent, Task, Crew
from langchain_openai import ChatOpenAI
from langchain_anthropic import ChatAnthropic
from typing import Optional, Dict, Any
from utils.logger import get_logger
from utils.upstash_sync import UpstashSync

logger = get_logger(name="context_sync_agent")


class ContextSyncAgent:
    def __init__(self, llm_model: str = "claude-sonnet-4-5-20250929"):
        self.llm = self._get_llm(llm_model)
        self.upstash = UpstashSync()
        self.agent = Agent(
            role="Context Synchronization Specialist",
            goal="Synchronize and manage context across agent workflows",
            backstory="Expert in maintaining context consistency across distributed agent systems",
            verbose=True,
            llm=self.llm
        )
    
    def _get_llm(self, model: str):
        import os
        from dotenv import load_dotenv
        load_dotenv()
        
        if "claude" in model.lower():
            api_key = os.getenv("ANTHROPIC_API_KEY")
            if not api_key:
                raise ValueError("ANTHROPIC_API_KEY not found")
            return ChatAnthropic(model=model, api_key=api_key)
        else:
            api_key = os.getenv("OPENAI_API_KEY")
            if not api_key:
                raise ValueError("OPENAI_API_KEY not found")
            # Remove temperature parameter entirely for compatibility
            return ChatOpenAI(model=model, api_key=api_key)
    
    def save_context(self, key: str, context_data: Dict[str, Any], ttl: Optional[int] = None):
        logger.log_agent_start("ContextSyncAgent", task=f"Save context: {key}")
        
        try:
            import json
            context_json = json.dumps(context_data, default=str)  # Handle non-serializable types
            success = self.upstash.set(key, context_json, ttl=ttl)
            
            if success:
                logger.log_agent_end("ContextSyncAgent", success=True)
            else:
                logger.debug(f"Upstash save returned False for: {key}")  # Changed to debug level
            
            return success
        except Exception as e:
            logger.debug(f"Context sync skipped (Upstash unavailable): {str(e)[:100]}")  # Debug, not error
            return False
    
    def get_context(self, key: str) -> Optional[Dict[str, Any]]:
        logger.log_agent_start("ContextSyncAgent", task=f"Get context: {key}")
        
        try:
            context_json = self.upstash.get(key)
            if context_json:
                import json
                context_data = json.loads(context_json)
                logger.log_agent_end("ContextSyncAgent", success=True)
                return context_data
            return None
        except Exception as e:
            logger.log_error(e, context={"agent": "ContextSyncAgent", "action": "get"})
            logger.log_agent_end("ContextSyncAgent", success=False)
            return None
    
    def sync_context(self, workflow_id: str, step: int, data: Dict[str, Any]):
        context_key = f"{workflow_id}:step:{step}"
        return self.save_context(context_key, data)
