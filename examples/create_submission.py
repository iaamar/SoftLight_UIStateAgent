#!/usr/bin/env python3
"""
Script to create the Softlight submission package
"""

import requests
import json
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).parent.parent))
from utils.dataset_exporter import DatasetExporter


# Define the tasks to capture for submission
SUBMISSION_TASKS = [
    # Linear
    {
        "app_name": "linear",
        "app_url": "https://linear.app",
        "task_query": "How do I create a new project?"
    },
    {
        "app_name": "linear",
        "app_url": "https://linear.app",
        "task_query": "How do I filter issues by status?"
    },
    # Notion
    {
        "app_name": "notion",
        "app_url": "https://www.notion.so",
        "task_query": "How do I create a database?"
    },
    {
        "app_name": "notion",
        "app_url": "https://www.notion.so",
        "task_query": "How do I filter a database view?"
    },
    # GitHub
    {
        "app_name": "github",
        "app_url": "https://github.com",
        "task_query": "How do I create a new repository?"
    }
]


def capture_tasks():
    """Capture all tasks for submission"""
    print("🚀 Capturing tasks for Softlight submission...")
    print("=" * 60)
    
    results = []
    
    for i, task in enumerate(SUBMISSION_TASKS, 1):
        print(f"\n📋 Task {i}/{len(SUBMISSION_TASKS)}: {task['task_query']}")
        print(f"   App: {task['app_name']}")
        print("-" * 40)
        
        try:
            response = requests.post(
                "http://localhost:8000/api/v1/execute",
                json=task,
                timeout=120  # 2 minutes per task
            )
            
            if response.status_code == 200:
                result = response.json()
                print(f"✅ Success! Captured {len(result['screenshots'])} screenshots")
                
                # Add to results
                results.append({
                    "app_name": task["app_name"],
                    "task_query": task["task_query"],
                    "screenshots": result["screenshots"],
                    "step_descriptions": result.get("step_descriptions", []),
                    "success": result["success"],
                    "steps_completed": result["steps_completed"]
                })
            else:
                print(f"❌ Failed: {response.status_code}")
                print(response.json())
                
        except Exception as e:
            print(f"❌ Error: {str(e)}")
    
    return results


def create_submission_package(results):
    """Create the final submission package"""
    print("\n\n📦 Creating submission package...")
    print("=" * 60)
    
    exporter = DatasetExporter()
    
    description = """
### Technical Implementation

The system uses a multi-agent architecture with CrewAI for intelligent navigation planning and Playwright for robust browser automation. Key innovations include:

1. **Modal Detection**: Automatically detects and captures modal dialogs using role attributes and CSS patterns
2. **Form State Progression**: Captures forms at multiple stages of completion
3. **Session Persistence**: Maintains authenticated sessions across tasks
4. **Smart Navigation**: Agents analyze DOM to generate precise CSS selectors
5. **Error Recovery**: Fallback mechanisms for dynamic content and selector resolution

### Challenges Solved

1. **Non-URL States**: Many UI states (modals, dropdowns) don't change the URL. The system detects these through DOM changes and visual cues.
2. **Dynamic Content**: Modern SPAs load content dynamically. The system uses intelligent waiting strategies and state detection.
3. **Authentication**: Supports both traditional login and OAuth flows with session persistence.
4. **Cross-App Compatibility**: Template system allows quick adaptation to different app structures.

### Code Quality

- Modular architecture with clear separation of concerns
- Comprehensive error handling and logging
- Type hints and documentation throughout
- Docker support for easy deployment
"""
    
    zip_path = exporter.create_submission_package(
        results,
        author="UI State Agent System",
        description=description
    )
    
    print(f"✅ Submission package created: {zip_path}")
    print("\n📋 Next steps:")
    print("1. Review the dataset in data/exports/softlight_submission/")
    print("2. Record a Loom video demonstrating the system")
    print("3. Push code to GitHub")
    print(f"4. Email the dataset ({zip_path}) to rohan@softlight.com")


def main():
    """Main submission creator"""
    print("🤖 Softlight Submission Creator")
    print("=" * 60)
    
    # Check if server is running
    try:
        response = requests.get("http://localhost:8000/health")
        if response.status_code != 200:
            print("❌ Backend server not responding. Please run: docker compose up")
            return
    except:
        print("❌ Cannot connect to backend. Please run: docker compose up")
        return
    
    # Capture tasks
    results = capture_tasks()
    
    if len(results) < 3:
        print("\n⚠️  Warning: Less than 3 tasks captured successfully")
        print("Consider running individual tasks manually for better results")
    
    # Create submission
    create_submission_package(results)
    
    print("\n✨ Submission preparation complete!")


if __name__ == "__main__":
    main()
