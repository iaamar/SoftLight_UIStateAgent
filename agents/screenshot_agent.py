from crewai import Agent, Task, Crew
from langchain_openai import ChatOpenAI
from langchain_anthropic import ChatAnthropic
from typing import Optional, Dict, Any
from utils.logger import get_logger
from utils.browser_controller import BrowserController

logger = get_logger(name="screenshot_agent")


class ScreenshotAgent:
    def __init__(self, browser: BrowserController, llm_model: str = "gpt-4o"):
        self.browser = browser
        self.llm = self._get_llm(llm_model)
        self.agent = Agent(
            role="Screenshot Capture Specialist",
            goal="Capture screenshots at strategic UI states during workflow execution",
            backstory="Expert in identifying important UI moments that need documentation",
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
    
    async def capture_screenshot(self, app: str, task: str, step: int, context: Optional[str] = None) -> str:
        logger.log_agent_start("ScreenshotAgent", task=f"Step {step}")
        
        try:
            await self.browser.wait_for_load_state("networkidle")
            
            screenshot_path = await self.browser.screenshot(
                app=app,
                task=task,
                step=step,
                full_page=True
            )
            
            task = Task(
                description=f"""
                Analyze the screenshot taken at step {step}.
                Context: {context or 'No additional context'}
                
                Determine if this screenshot captures:
                1. A significant UI state change
                2. Important information visible
                3. Modal or form state
                4. Success/error messages
                
                Return assessment of screenshot quality and relevance.
                """,
                expected_output="An assessment of the screenshot quality and relevance, indicating whether it captures significant UI state changes.",
                agent=self.agent
            )
            
            crew = Crew(agents=[self.agent], tasks=[task])
            crew.kickoff()
            
            logger.log_agent_end("ScreenshotAgent", success=True)
            return screenshot_path
        except Exception as e:
            logger.log_error(e, context={"agent": "ScreenshotAgent", "step": step})
            logger.log_agent_end("ScreenshotAgent", success=False)
            raise
