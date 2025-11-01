#!/usr/bin/env python3
"""
Example script to test UI state capture workflows
"""

import requests
import json
from typing import List, Dict, Any


BASE_URL = "http://localhost:8000"


def test_single_task(app_name: str, app_url: str, task_query: str) -> Dict[str, Any]:
    """Test a single task capture"""
    print(f"\n📋 Testing: {task_query} on {app_name}")
    print("-" * 50)
    
    response = requests.post(
        f"{BASE_URL}/api/v1/execute",
        json={
            "task_query": task_query,
            "app_url": app_url,
            "app_name": app_name
        }
    )
    
    if response.status_code == 200:
        result = response.json()
        print(f"✅ Success! Captured {result['steps_completed']} steps")
        print(f"📸 Screenshots: {len(result['screenshots'])}")
        if result.get('step_descriptions'):
            print("\n📝 Steps captured:")
            for i, desc in enumerate(result['step_descriptions'], 1):
                print(f"   {i}. {desc}")
        return result
    else:
        print(f"❌ Failed: {response.status_code}")
        print(response.json())
        return None


def export_task(app_name: str, app_url: str, task_query: str) -> str:
    """Export a task's dataset"""
    print(f"\n📦 Exporting dataset for: {task_query}")
    
    response = requests.post(
        f"{BASE_URL}/api/v1/export-task",
        json={
            "task_query": task_query,
            "app_url": app_url,
            "app_name": app_name
        }
    )
    
    if response.status_code == 200:
        result = response.json()
        print(f"✅ Dataset exported to: {result['export_path']}")
        return result['export_path']
    else:
        print(f"❌ Export failed: {response.status_code}")
        return None


def batch_export(tasks: List[Dict[str, str]]) -> str:
    """Export multiple tasks as a dataset"""
    print(f"\n📦 Batch exporting {len(tasks)} tasks...")
    
    response = requests.post(
        f"{BASE_URL}/api/v1/export-batch",
        json=tasks
    )
    
    if response.status_code == 200:
        result = response.json()
        print(f"✅ Dataset exported to: {result['export_path']}")
        print(f"   Total tasks: {result['total_tasks']}")
        print(f"   Successful: {result['successful_tasks']}")
        return result['export_path']
    else:
        print(f"❌ Batch export failed: {response.status_code}")
        return None


# Example workflows for different applications
EXAMPLE_WORKFLOWS = {
    "linear": {
        "url": "https://linear.app",
        "tasks": [
            "How do I create a new project in Linear?",
            "How do I create a new issue in Linear?",
            "How do I filter issues by status in Linear?",
            "How do I change project settings in Linear?"
        ]
    },
    "notion": {
        "url": "https://www.notion.so",
        "tasks": [
            "How do I create a new page in Notion?",
            "How do I create a database in Notion?",
            "How do I filter a database view in Notion?",
            "How do I share a page in Notion?"
        ]
    },
    "asana": {
        "url": "https://app.asana.com",
        "tasks": [
            "How do I create a new project in Asana?",
            "How do I create a task in Asana?",
            "How do I set up a team in Asana?",
            "How do I use the timeline view in Asana?"
        ]
    },
    "github": {
        "url": "https://github.com",
        "tasks": [
            "How do I create a new repository?",
            "How do I create an issue?",
            "How do I create a pull request?",
            "How do I manage repository settings?"
        ]
    }
}


def test_app_workflows(app_name: str):
    """Test all workflows for a specific app"""
    if app_name not in EXAMPLE_WORKFLOWS:
        print(f"❌ Unknown app: {app_name}")
        return
    
    app_config = EXAMPLE_WORKFLOWS[app_name]
    print(f"\n🚀 Testing {app_name.title()} workflows")
    print("=" * 60)
    
    results = []
    for task in app_config["tasks"]:
        result = test_single_task(app_name, app_config["url"], task)
        if result:
            results.append({
                "app_name": app_name,
                "app_url": app_config["url"],
                "task_query": task
            })
    
    # Export as batch
    if results:
        batch_export(results)


def main():
    """Main test runner"""
    print("🤖 SoftLight UI State Agent - Workflow Tester")
    print("=" * 60)
    
    # Test individual workflows
    print("\n1️⃣ Testing Linear - Create Project")
    test_single_task("linear", "https://linear.app", "How do I create a project?")
    
    print("\n2️⃣ Testing Notion - Create Database")
    test_single_task("notion", "https://www.notion.so", "How do I create a database?")
    
    print("\n3️⃣ Testing GitHub - Create Repository")
    test_single_task("github", "https://github.com", "How do I create a repository?")
    
    # Test batch export
    print("\n4️⃣ Testing Batch Export")
    batch_tasks = [
        {"app_name": "linear", "app_url": "https://linear.app", "task_query": "create project"},
        {"app_name": "linear", "app_url": "https://linear.app", "task_query": "create issue"},
        {"app_name": "notion", "app_url": "https://www.notion.so", "task_query": "create page"},
        {"app_name": "github", "app_url": "https://github.com", "task_query": "create repository"},
        {"app_name": "asana", "app_url": "https://app.asana.com", "task_query": "create project"}
    ]
    batch_export(batch_tasks)
    
    print("\n✨ Testing complete!")


if __name__ == "__main__":
    main()
