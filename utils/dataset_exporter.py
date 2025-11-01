"""
Dataset export functionality for captured UI states
"""

import os
import json
import shutil
from pathlib import Path
from typing import Dict, List, Any, Optional
from datetime import datetime
import markdown


class DatasetExporter:
    """Export captured UI states in organized format"""
    
    def __init__(self, data_dir: str = "data"):
        self.data_dir = Path(data_dir)
        self.screenshots_dir = self.data_dir / "screenshots"
        self.exports_dir = self.data_dir / "exports"
        self.exports_dir.mkdir(parents=True, exist_ok=True)
    
    def export_task_dataset(
        self,
        app_name: str,
        task_query: str,
        screenshots: List[str],
        step_descriptions: List[str],
        metadata: Optional[Dict[str, Any]] = None
    ) -> str:
        """Export a single task's UI states"""
        
        # Create export directory with timestamp
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        export_name = f"{app_name}_{task_query.replace(' ', '_')}_{timestamp}"
        export_path = self.exports_dir / export_name
        export_path.mkdir(parents=True, exist_ok=True)
        
        # Copy screenshots
        screenshots_export = export_path / "screenshots"
        screenshots_export.mkdir(exist_ok=True)
        
        exported_screenshots = []
        for i, screenshot in enumerate(screenshots):
            src_path = Path(screenshot)
            if src_path.exists():
                dst_name = f"step_{i:03d}_{src_path.name}"
                dst_path = screenshots_export / dst_name
                shutil.copy2(src_path, dst_path)
                exported_screenshots.append(dst_name)
        
        # Create metadata JSON
        task_metadata = {
            "app_name": app_name,
            "task_query": task_query,
            "capture_date": datetime.now().isoformat(),
            "screenshots_count": len(screenshots),
            "steps": [
                {
                    "step_number": i + 1,
                    "screenshot": exported_screenshots[i] if i < len(exported_screenshots) else None,
                    "description": step_descriptions[i] if i < len(step_descriptions) else f"Step {i + 1}"
                }
                for i in range(max(len(screenshots), len(step_descriptions)))
            ]
        }
        
        if metadata:
            task_metadata.update(metadata)
        
        # Save metadata
        with open(export_path / "metadata.json", "w") as f:
            json.dump(task_metadata, f, indent=2)
        
        # Create README
        self._create_readme(export_path, task_metadata)
        
        return str(export_path)
    
    def export_batch_dataset(
        self,
        tasks: List[Dict[str, Any]],
        export_name: Optional[str] = None
    ) -> str:
        """Export multiple tasks as a dataset"""
        
        # Create main export directory
        if not export_name:
            export_name = f"dataset_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        
        export_path = self.exports_dir / export_name
        export_path.mkdir(parents=True, exist_ok=True)
        
        # Export each task
        task_exports = []
        for i, task in enumerate(tasks):
            task_dir = export_path / f"{i+1:02d}_{task['app_name']}_{task['task_query'].replace(' ', '_')}"
            task_dir.mkdir(exist_ok=True)
            
            # Copy screenshots
            screenshots_dir = task_dir / "screenshots"
            screenshots_dir.mkdir(exist_ok=True)
            
            exported_screenshots = []
            for j, screenshot in enumerate(task.get("screenshots", [])):
                src_path = Path(screenshot)
                if src_path.exists():
                    dst_name = f"step_{j:03d}.png"
                    dst_path = screenshots_dir / dst_name
                    shutil.copy2(src_path, dst_path)
                    exported_screenshots.append(dst_name)
            
            # Task metadata
            task_metadata = {
                "app_name": task["app_name"],
                "task_query": task["task_query"],
                "capture_date": task.get("capture_date", datetime.now().isoformat()),
                "screenshots_count": len(exported_screenshots),
                "steps": [
                    {
                        "step_number": j + 1,
                        "screenshot": exported_screenshots[j] if j < len(exported_screenshots) else None,
                        "description": task.get("step_descriptions", [])[j] if j < len(task.get("step_descriptions", [])) else f"Step {j + 1}"
                    }
                    for j in range(max(len(exported_screenshots), len(task.get("step_descriptions", []))))
                ]
            }
            
            with open(task_dir / "metadata.json", "w") as f:
                json.dump(task_metadata, f, indent=2)
            
            task_exports.append({
                "task_number": i + 1,
                "app_name": task["app_name"],
                "task_query": task["task_query"],
                "screenshots_count": len(exported_screenshots),
                "directory": task_dir.name
            })
        
        # Create main metadata
        dataset_metadata = {
            "export_date": datetime.now().isoformat(),
            "total_tasks": len(tasks),
            "tasks": task_exports
        }
        
        with open(export_path / "dataset_metadata.json", "w") as f:
            json.dump(dataset_metadata, f, indent=2)
        
        # Create main README
        self._create_dataset_readme(export_path, dataset_metadata)
        
        return str(export_path)
    
    def _create_readme(self, export_path: Path, metadata: Dict[str, Any]):
        """Create README for single task export"""
        readme_content = f"""# UI State Capture: {metadata['app_name']} - {metadata['task_query']}

## Overview
This dataset contains captured UI states for the task: **{metadata['task_query']}**

- **Application**: {metadata['app_name']}
- **Capture Date**: {metadata['capture_date']}
- **Total Screenshots**: {metadata['screenshots_count']}

## Captured Steps

"""
        
        for step in metadata['steps']:
            readme_content += f"""### Step {step['step_number']}
**Description**: {step['description']}
"""
            if step['screenshot']:
                readme_content += f"**Screenshot**: [`{step['screenshot']}`](screenshots/{step['screenshot']})\n\n"
                readme_content += f"![Step {step['step_number']}](screenshots/{step['screenshot']})\n\n"
            readme_content += "---\n\n"
        
        readme_content += """## Usage

This dataset can be used to:
1. Train AI models on UI navigation patterns
2. Create documentation for the workflow
3. Test UI automation scripts
4. Analyze UI/UX patterns

## Files Structure
```
.
├── metadata.json       # Detailed metadata for this task
├── README.md          # This file
└── screenshots/       # Directory containing all screenshots
    ├── step_001_*.png
    ├── step_002_*.png
    └── ...
```
"""
        
        with open(export_path / "README.md", "w") as f:
            f.write(readme_content)
    
    def _create_dataset_readme(self, export_path: Path, metadata: Dict[str, Any]):
        """Create README for batch dataset export"""
        readme_content = f"""# UI State Capture Dataset

## Overview
This dataset contains captured UI states for multiple tasks across different applications.

- **Export Date**: {metadata['export_date']}
- **Total Tasks**: {metadata['total_tasks']}

## Tasks Included

| # | Application | Task | Screenshots | Directory |
|---|-------------|------|-------------|-----------|
"""
        
        for task in metadata['tasks']:
            readme_content += f"| {task['task_number']} | {task['app_name']} | {task['task_query']} | {task['screenshots_count']} | `{task['directory']}` |\n"
        
        readme_content += """

## Dataset Structure
```
.
├── dataset_metadata.json    # Overall dataset metadata
├── README.md               # This file
└── [task_directories]/     # Individual task directories
    ├── metadata.json       # Task-specific metadata
    └── screenshots/        # Screenshots for the task
```

## Usage

This dataset is designed for:
1. **AI Training**: Train models to understand UI navigation patterns
2. **Documentation**: Create step-by-step guides for common workflows
3. **Testing**: Validate UI automation scripts
4. **Analysis**: Study UI/UX patterns across different applications

## How to Use

1. Load the `dataset_metadata.json` to understand the overall structure
2. Navigate to individual task directories for specific workflows
3. Each task directory contains:
   - `metadata.json`: Detailed information about the task
   - `screenshots/`: All captured UI states in order

## Applications Covered
"""
        
        apps = set(task['app_name'] for task in metadata['tasks'])
        for app in sorted(apps):
            readme_content += f"- **{app}**\n"
        
        with open(export_path / "README.md", "w") as f:
            f.write(readme_content)
    
    def create_submission_package(
        self,
        tasks: List[Dict[str, Any]],
        author: str = "Agent B",
        description: str = ""
    ) -> str:
        """Create a submission package for the Softlight assignment"""
        
        # Export the dataset
        export_path = self.export_batch_dataset(tasks, "softlight_submission")
        export_path = Path(export_path)
        
        # Create submission README
        submission_readme = f"""# SoftLight UI State Capture Submission

**Author**: {author}
**Date**: {datetime.now().strftime('%Y-%m-%d')}

## Overview

This submission contains captured UI states for {len(tasks)} tasks across multiple web applications, demonstrating the capability to capture both URL-based and non-URL UI states (modals, dropdowns, form states).

## Technical Implementation

### Architecture
- **Browser Automation**: Playwright for robust cross-browser support
- **AI Agents**: CrewAI-based modular agents for intelligent navigation
- **State Capture**: Enhanced screenshot capture for modals and dynamic content
- **Session Persistence**: Browser context saving for authenticated sessions

### Key Features
1. **Modal Detection**: Automatically detects and captures modal/dialog states
2. **Form State Capture**: Captures forms at different completion stages
3. **Hover States**: Captures dropdown menus and tooltips
4. **Error Recovery**: Robust error handling and retry logic
5. **OAuth Support**: Handles multiple authentication methods

## Captured Tasks

{self._generate_task_summary(tasks)}

## Dataset Structure

```
softlight_submission/
├── dataset_metadata.json      # Overall metadata
├── README.md                  # This file
├── SUBMISSION_NOTES.md        # Additional notes
└── [task_folders]/           # Individual task captures
    ├── metadata.json         # Task metadata
    └── screenshots/          # UI state screenshots
```

## How to Review

1. Start with this README for an overview
2. Check `dataset_metadata.json` for the complete task list
3. Navigate to individual task folders to see the captured UI states
4. Each screenshot is named sequentially (step_001.png, step_002.png, etc.)
5. The `metadata.json` in each folder provides descriptions for each step

## Technical Details

{description}

## Contact

For any questions or clarifications, please reach out.

---
*This dataset was captured using the SoftLight UI State Agent system*
"""
        
        with open(export_path / "SUBMISSION_README.md", "w") as f:
            f.write(submission_readme)
        
        # Create a zip file for easy submission
        shutil.make_archive(str(export_path), 'zip', export_path)
        
        return f"{export_path}.zip"
    
    def _generate_task_summary(self, tasks: List[Dict[str, Any]]) -> str:
        """Generate a summary of captured tasks"""
        summary = ""
        
        # Group by app
        apps = {}
        for task in tasks:
            app = task['app_name']
            if app not in apps:
                apps[app] = []
            apps[app].append(task)
        
        for app, app_tasks in apps.items():
            summary += f"\n### {app.title()}\n\n"
            for i, task in enumerate(app_tasks, 1):
                summary += f"{i}. **{task['task_query']}** - {len(task.get('screenshots', []))} states captured\n"
        
        return summary
