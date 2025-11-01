#!/usr/bin/env python3
"""
Demo script for the enhanced SoftLight UI State Capture System
This demonstrates the robust capabilities of the enhanced system
"""

import asyncio
import sys
import os
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

from utils.browser_controller import BrowserController
from graph.workflow import AgentWorkflow
from examples.workflow_examples import get_test_workflows
import json
from datetime import datetime


async def demo_basic_navigation():
    """Demonstrate basic navigation and screenshot capture"""
    print("\n" + "="*60)
    print("DEMO: Basic Navigation with Enhanced Features")
    print("="*60)
    
    browser = None
    try:
        # Create enhanced browser controller
        browser = BrowserController(
            headless=False,  # Show browser for demo
            viewport_width=1920,
            viewport_height=1080
        )
        
        await browser.start()
        print("✓ Browser started with enhanced controller")
        
        # Navigate to a website
        await browser.navigate("https://github.com")
        await browser.wait_for_stable_page()
        print("✓ Navigated to GitHub with stability detection")
        
        # Demonstrate modal detection
        modals = await browser.detect_and_handle_modals()
        print(f"✓ Modal detection: Found {len(modals)} modals")
        
        # Demonstrate form detection
        forms = await browser.detect_forms()
        print(f"✓ Form detection: Found {len(forms)} forms")
        
        # Capture enhanced screenshot
        screenshot_path = await browser.smart_screenshot(
            app="demo",
            task="basic_navigation",
            step=0,
            highlight_elements=["a:has-text('Sign up')"] if await browser.evaluate_selector("a:has-text('Sign up')") else []
        )
        print(f"✓ Enhanced screenshot captured: {screenshot_path}")
        
        # Demonstrate element finding by text
        signup_selector = await browser.find_element_by_text("Sign up", "a")
        if signup_selector:
            print(f"✓ Found 'Sign up' button with selector: {signup_selector}")
        
    finally:
        if browser:
            await browser.close()
            print("✓ Browser closed")


async def demo_workflow_execution():
    """Demonstrate full workflow execution with error recovery"""
    print("\n" + "="*60)
    print("DEMO: Complete Workflow Execution")
    print("="*60)
    
    browser = None
    try:
        # Setup browser with session persistence
        session_file = Path("data/sessions/demo_session.json")
        session_file.parent.mkdir(parents=True, exist_ok=True)
        
        browser = BrowserController(
            headless=True,
            context_state_file=str(session_file)
        )
        
        await browser.start()
        print("✓ Browser started with session persistence")
        
        # Create enhanced workflow
        workflow = AgentWorkflow(
            browser=browser,
            llm_model="gpt-4o",
            capture_metadata=True
        )
        
        # Execute a simple workflow
        print("\nExecuting workflow: Navigate to GitHub pricing page")
        result = await workflow.execute(
            task_query="How do I navigate to the pricing page?",
            app_url="https://github.com",
            app_name="github_demo",
            task_name="navigate_to_pricing"
        )
        
        print(f"\nWorkflow Results:")
        print(f"  Success: {result['success']}")
        print(f"  Screenshots captured: {len(result['screenshots'])}")
        print(f"  Steps completed: {result['steps_completed']}")
        print(f"  UI states captured: {result['ui_states_captured']}")
        print(f"  Modals detected: {result['modals_detected']}")
        print(f"  Execution time: {result['execution_time']:.2f}s")
        
        if result['step_descriptions']:
            print("\nStep Descriptions:")
            for i, desc in enumerate(result['step_descriptions']):
                print(f"  {i+1}. {desc}")
        
    except Exception as e:
        print(f"❌ Error: {str(e)}")
    finally:
        if browser:
            await browser.close()
            print("\n✓ Workflow completed")


async def demo_error_recovery():
    """Demonstrate error recovery mechanisms"""
    print("\n" + "="*60)
    print("DEMO: Error Recovery and Robustness")
    print("="*60)
    
    browser = None
    try:
        browser = BrowserController(headless=True)
        await browser.start()
        print("✓ Browser started")
        
        # Navigate to a page
        await browser.navigate("https://example.com")
        
        # Try clicking non-existent element (will use retry logic)
        print("\nTesting error recovery for non-existent element:")
        try:
            await browser.click("#non-existent-button", retry=True)
        except Exception as e:
            print(f"✓ Gracefully handled error: {type(e).__name__}")
        
        # Demonstrate alternative selector finding
        print("\nTesting alternative selector finding:")
        # Create a mock button for testing
        await browser.page.evaluate("""
            document.body.innerHTML += '<button id="test-btn" class="demo-button">Click Me</button>';
        """)
        
        alt_selector = await browser.find_alternative_selector("#test-btn")
        print(f"✓ Found alternative selector: {alt_selector}")
        
        # Test wait for stable page with dynamic content
        print("\nTesting dynamic content handling:")
        await browser.page.evaluate("""
            // Simulate dynamic content loading
            setTimeout(() => {
                document.body.innerHTML += '<div class="dynamic-content">Loaded!</div>';
            }, 1000);
        """)
        
        await browser.wait_for_stable_page(max_wait=3.0)
        print("✓ Successfully waited for dynamic content")
        
    finally:
        if browser:
            await browser.close()


async def demo_comprehensive_capture():
    """Demonstrate comprehensive UI state capture"""
    print("\n" + "="*60)
    print("DEMO: Comprehensive UI State Capture")
    print("="*60)
    
    browser = None
    try:
        browser = BrowserController(headless=True)
        await browser.start()
        
        # Navigate to a complex page
        await browser.navigate("https://www.notion.so")
        await browser.wait_for_stable_page()
        
        print("✓ Navigated to Notion")
        
        # Capture full workflow state
        ui_state = await browser.capture_full_workflow_state()
        
        print("\nCaptured UI State Information:")
        print(f"  URL: {ui_state['url']}")
        print(f"  Title: {ui_state['title']}")
        print(f"  Viewport: {ui_state['viewport']['width']}x{ui_state['viewport']['height']}")
        print(f"  Modals detected: {len(ui_state['modals'])}")
        print(f"  Forms detected: {len(ui_state['forms'])}")
        print(f"  Navigation history entries: {len(ui_state['navigation_history'])}")
        
        # Save state to file
        state_file = Path("data/demo_ui_state.json")
        state_file.parent.mkdir(parents=True, exist_ok=True)
        with open(state_file, "w") as f:
            json.dump(ui_state, f, indent=2, default=str)
        print(f"\n✓ UI state saved to: {state_file}")
        
    finally:
        if browser:
            await browser.close()


async def main():
    """Run all demos"""
    print("\n🚀 SoftLight Enhanced UI State Capture System Demo")
    print("=" * 60)
    
    demos = [
        ("Basic Navigation", demo_basic_navigation),
        ("Workflow Execution", demo_workflow_execution),
        ("Error Recovery", demo_error_recovery),
        ("Comprehensive State Capture", demo_comprehensive_capture)
    ]
    
    for demo_name, demo_func in demos:
        try:
            print(f"\n🔄 Running: {demo_name}")
            await demo_func()
        except Exception as e:
            print(f"\n❌ Demo '{demo_name}' failed: {str(e)}")
        
        # Small delay between demos
        await asyncio.sleep(2)
    
    print("\n" + "="*60)
    print("✅ All demos completed!")
    print("=" * 60)
    
    # Summary
    print("\n📊 Enhanced Features Demonstrated:")
    print("  • Robust error handling with retry mechanisms")
    print("  • Dynamic content detection and waiting")
    print("  • Modal and popup detection")
    print("  • Form field detection and tracking")
    print("  • Alternative selector finding")
    print("  • Comprehensive UI state capture")
    print("  • Session persistence")
    print("  • Enhanced screenshot with highlighting")
    print("  • Detailed execution logging")
    print("  • Workflow metadata capture")
    
    print("\n💡 Next Steps:")
    print("  1. Configure your .env file with API keys")
    print("  2. Run the backend: python backend/main_enhanced.py")
    print("  3. Execute workflows via the API")
    print("  4. Review captured data in the data/ directory")


if __name__ == "__main__":
    # Check for required environment variables
    if not os.getenv("OPENAI_API_KEY"):
        print("⚠️  Warning: OPENAI_API_KEY not set. Some features may not work.")
        print("   Please set it in your .env file or environment")
    
    # Run the demos
    asyncio.run(main())
