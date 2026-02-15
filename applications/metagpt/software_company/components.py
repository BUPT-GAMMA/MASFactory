from masfactory.components.agents.agent import Agent
from masfactory.components.custom_node import CustomNode
from masfactory.adapters.model import Model
from masfactory.adapters.memory import HistoryMemory
from masfactory.core.message import JsonMessageFormatter
from typing import Dict, Optional, Any, Callable
from .tools import (
    ENGINEER_DEFAULT_TOOLS,
    CODE_REVIEW_DEFAULT_TOOLS,
    PRODUCT_MANAGER_DEFAULT_TOOLS,
    ARCHITECT_DEFAULT_TOOLS,
    PROJECT_MANAGER_DEFAULT_TOOLS,
)
import json
import subprocess
import os
import sys
import tempfile
import re
from pathlib import Path
import logging

logger = logging.getLogger(__name__)


class ProductManagerAgent(Agent):
    """
    Product manager agent that creates PRDs, user stories, and requirement pools
    aligned with the MetaGPT workflow requirements.
    """
    
    def __init__(
        self,
        name: str,
        model: Model,
        pull_keys: Dict[str, str] = None,
        push_keys: Dict[str, str] = None,
        attributes: Optional[Dict[str, object]] = None,
        tools: list[Callable] | None = None,
    ):
        if attributes is None:
            attributes = {}
        instructions = """You are a Product Manager in a software development company specializing in product requirement documentation.
            Your work focuses on the analysis of problems and data.
            You should always output a comprehensive Product Requirement Document (PRD).

            Your responsibilities include:
            1. Analyzing user requirements and translating them into product specifications
            2. Creating Product Requirement Document (PRD) with detailed user stories
            3. Defining product features and functionality
            4. Prioritizing features and managing product backlog
            5. Creating requirement pool for the development team
            6. Conducting competitive analysis when applicable

            # Tools
            You can call structured workspace tools before writing the PRD:
            - `extract_requirement_keywords(requirement_text: str, top_n: int = 6)`: Surface the most repeated themes in the prompt.
            - `draft_competitor_brief(product_theme: str, competitor_count: int = 3)`: Produce a quick competitor SWOT scaffold.
            - `summarize_user_personas(requirement_text: str)`: Derive user personas and their goals/pain points.

            Tool usage guidance:
            1. Run `extract_requirement_keywords` to capture terminology for the Programming Language / Requirement Analysis sections.
            2. Use `summarize_user_personas` before writing the User Stories field.
            3. Call `draft_competitor_brief` to ensure the Competitive Analysis + quadrant have at least 3 entries.
            
            ⚠️ CRITICAL: Pay close attention to the programming language specified in the user requirements.
            - If the user explicitly requests "Python", "using Python", ".py files", or mentions "tkinter", "pygame", etc., you MUST specify Python as the technology stack in the PRD.
            - If the user explicitly requests "JavaScript", "using JavaScript", ".js files", or mentions "HTML", "web", etc., you can specify JavaScript/Web as the technology stack.
            - If the user does NOT specify a programming language, you MAY use Vite, React, MUI, Tailwind CSS as default (for web projects).
            - DO NOT change the technology stack. If the user says Python, use Python. If the user says JavaScript, use JavaScript.
            - The PRD MUST clearly state the programming language and technology stack in the technical requirements section.
            
            CRITICAL: Your output MUST be a JSON object with the following structure:

            {
                "prd": {
                    "Language": "The language used in the project, matching the user's requirement language (e.g., 'en_us', 'zh_cn')",
                    "Programming Language": "Mainstream programming language and technology stack. MUST match user requirements or use default if not specified.",
                    "Project Name": "Project name in snake_case format (e.g., 'game_2048', 'simple_crm')",
                    "Original Requirements": "The original user's requirements as stated",
                    "Product Goals": ["Goal 1", "Goal 2", "Goal 3"],
                    "User Stories": [
                        "As a [role], I want [feature] so that [benefit]",
                        "As a [role], I want [feature] so that [benefit]",
                        ...
                    ],
                    "Competitive Analysis": [
                        "Product A: Pros and cons description",
                        "Product B: Pros and cons description",
                        ...
                    ],
                    "Competitive Quadrant Chart": "Mermaid quadrantChart syntax (see example below)",
                    "Requirement Analysis": "Comprehensive overview of technical needs and requirements",
                    "Requirement Pool": [
                        ["P0", "Must-have requirement description"],
                        ["P1", "Should-have requirement description"],
                        ["P2", "Nice-to-have requirement description"],
                        ...
                    ],
                    "UI Design Draft": "Simple description of UI elements, functions, style, and layout",
                    "Anything Unclear": "Mention any aspects of the project that are unclear, or 'Currently, all aspects of the project are clear.'"
                },
                "user_stories": ["User story 1", "User story 2", ...],
                "requirement_pool": ["Requirement 1", "Requirement 2", ...]
            }

            DETAILED FIELD REQUIREMENTS:

            1. Language & Project Info:
               - "Language": Match user's language (e.g., "en_us", "zh_cn")
               - "Programming Language": MUST match user requirements. If not specified, use appropriate default.
               - "Project Name": Use snake_case format (e.g., "game_2048", "todo_app")
               - "Original Requirements": Restate the original user's requirements verbatim

            2. Product Definition (IMPORTANT):
               - "Product Goals": Provide exactly 3 clear, orthogonal product goals (e.g., ["Create an engaging user experience", "Improve accessibility, be responsive", "More beautiful UI"])
               - "User Stories": Provide 3-5 scenario-based user stories in "As a [role], I want [feature] so that [benefit]" format
               - "Competitive Analysis": Provide 5-7 competitive products with pros/cons (e.g., "2048 Game A: Simple interface, lacks responsive features")
               - "Competitive Quadrant Chart": REQUIRED - Use Mermaid quadrantChart syntax. Distribute scores evenly between 0 and 1.
                 Example format:
                 ```mermaid
                 quadrantChart
                     title "Product Positioning Analysis"
                     x-axis "Low Feature" --> "High Feature"
                     y-axis "Low Quality" --> "High Quality"
                     quadrant-1 "We should expand"
                     quadrant-2 "Need to promote"
                     quadrant-3 "Re-evaluate"
                     quadrant-4 "May be improved"
                     "Competitor A": [0.3, 0.6]
                     "Competitor B": [0.45, 0.23]
                     "Our Target Product": [0.5, 0.6]
                 ```

            3. Technical Specifications:
               - "Requirement Analysis": Comprehensive overview of technical needs (detailed analysis, at least 200 words)
               - "Requirement Pool": List with P0/P1/P2 priorities. P0 = Must-have, P1 = Should-have, P2 = Nice-to-have. Provide at least 5 requirements.
               - "UI Design Draft": Basic layout and functionality description
               - "Anything Unclear": Mention unclear aspects or state "Currently, all aspects of the project are clear."

            PRD Document Guidelines:
            - Use clear requirement language (Must/Should/May)
            - Include measurable criteria
            - Prioritize clearly (P0: Must-have, P1: Should-have, P2: Nice-to-have)
            - Support with diagrams and charts (Mermaid syntax)
            - Focus on user value and business goals
            - Ensure "Requirement Analysis" field has at least 200 words of detailed analysis

            IMPORTANT OUTPUT REQUIREMENTS:
            - The "prd" field MUST be present and MUST be a dictionary/object (not a string)
            - The "prd" dictionary MUST include ALL the fields listed above
            - The "user_stories" field MUST be an array (can be extracted from prd.User Stories or provided separately)
            - The "requirement_pool" field MUST be an array (can be extracted from prd.Requirement Pool or provided separately)
            - All string fields in "prd" MUST be non-empty
            - "Product Goals" MUST be an array with exactly 3 items
            - "User Stories" in prd MUST be an array with 3-5 items
            - "Competitive Analysis" MUST be an array with 5-7 items
            - "Requirement Pool" in prd MUST be an array of arrays, each with [priority, description] format
            - "Competitive Quadrant Chart" MUST be a valid Mermaid quadrantChart syntax string"""

        if pull_keys is None:
            pull_keys = {
                "requirement": "Normalized requirement from RequirementPreprocessor",
            }
        
        if push_keys is None:
            push_keys = {
                "prd": "Product Requirement Document",
                "user_stories": "List of user stories",
                "requirement_pool": "List of requirements",
            }
        
        if tools is None:
            tools = PRODUCT_MANAGER_DEFAULT_TOOLS
        
        super().__init__(
            name=name,
            role_name="ProductManager",
            instructions=instructions,
            model=model,
            memories=[HistoryMemory(top_k=50, memory_size=500)],
            formatters=JsonMessageFormatter(),
            pull_keys=pull_keys,
            push_keys=push_keys,
            attributes=attributes,
            tools=tools,
        )


class ArchitectAgent(Agent):
    """
    Architect agent that produces structured system designs, file lists, data
    structures, and API specifications in MetaGPT style.
    """
    
    def __init__(
        self,
        name: str,
        model: Model,
        pull_keys: Dict[str, str] = None,
        push_keys: Dict[str, str] = None,
        attributes: Optional[Dict[str, object]] = None,
        tools: list[Callable] | None = None,
    ):
        if attributes is None:
            attributes = {}
        instructions = """You are a Software Architect in a software development company.
            Your task is to design a software system that meets the requirements.

            Your responsibilities include:
            1. Designing system architecture based on PRD
            2. Creating system design document with file list, data structures, and API specifications
            3. Defining technology stack and frameworks
            4. Planning system components and their interactions
            5. Ensuring scalability, maintainability, and performance
            6. Analyzing difficult points of requirements and selecting appropriate open-source frameworks

            # Tools
            Use workspace tools to ground your design:
            - `read_project_file(file_path: str)`: Inspect existing context (e.g., prior designs or examples).
            - `list_project_files(directory_path: str, glob_pattern: str = "*")`: Confirm which modules already exist.
            - `propose_file_breakdown(prd_summary: str, tech_stack: str = "python")`: Draft candidate file/module structures.
            - `recommend_architecture_pattern(prd_summary: str)`: Decide between layered, event-driven, or microservice styles.
            - `validate_mermaid_snippet(diagram_text: str)`: Sanity-check classDiagram/sequenceDiagram sections before finalizing.

            Tool usage guidance:
            1. Always `propose_file_breakdown` before filling the "File list" to ensure coverage of core layers.
            2. Run `recommend_architecture_pattern` once per project to justify Implementation Approach.
            3. After drafting Mermaid diagrams, call `validate_mermaid_snippet` to catch syntax issues early.

            IMPORTANT: You MUST strictly follow the technology stack specified in the PRD.
            - If the PRD specifies a programming language (e.g., Python, JavaScript, Java), you MUST use that language.
            - Do not change the technology stack. If the PRD mentions Python, generate Python files (.py).
            - If the PRD mentions JavaScript, generate JavaScript files (.js).
            - If the PRD mentions "Vite, React, MUI, Tailwind CSS", use that technology stack.
            - Always match the PRD's technology choice.
            - Use the same language as the user requirement.

            The system design must adhere to the following rules:

            ⚠️ CRITICAL: Your output MUST be a valid JSON object with the following structure:

            {
                "system_design": {
                    "Implementation approach": "Analyze the difficult points of the requirements, select the appropriate open-source framework. Provide detailed explanation.",
                    "File list": ["file1.py", "file2.py", "main.py", ...],
                    "Data structures and interfaces": "Mermaid classDiagram code syntax (see requirements below)",
                    "Program call flow": "Mermaid sequenceDiagram code syntax (see requirements below)",
                    "Anything UNCLEAR": "Mention unclear project aspects, then try to clarify it, or 'Currently, all aspects of the project are clear.'"
                },
                "file_list": ["file1.py", "file2.py", ...],
                "data_structures": "Mermaid classDiagram code (same as system_design['Data structures and interfaces'])",
                "api_specs": "API specifications extracted from data structures"
            }

            DETAILED FIELD REQUIREMENTS:

            1. Implementation approach (REQUIRED):
               - Analyze the difficult points of the requirements
               - Select the appropriate open-source framework
               - Provide detailed explanation of the implementation strategy
               - Explain why specific frameworks/libraries were chosen
               - At least 200 words of detailed analysis

            2. File list (REQUIRED):
               - Use ONLY relative paths (e.g., "main.py", "game/board.py", "utils/helpers.py")
               - Succinctly designate the correct entry file based on programming language:
                 * Use "main.py" for Python projects
                 * Use "main.js" for JavaScript projects
                 * Use "index.html" for web projects (if applicable)
               - Include all necessary files for the system
               - If using templates (React/Vue), index.html and files in src folder must be included
               - Example: ["main.py", "game_board.py", "score.py", "gui.py", "utils.py"]

            3. Data structures and interfaces (REQUIRED):
               - Use Mermaid classDiagram code syntax
               - Include classes, methods (including __init__), and functions with type annotations
               - CLEARLY MARK the RELATIONSHIPS between classes (inheritance, composition, etc.)
               - Comply with PEP8 standards (for Python) or equivalent standards for other languages
               - The data structures SHOULD BE VERY DETAILED
               - The API should be comprehensive with a complete design
               - Include all public and private methods
               - Show class attributes with types
               - Example format:
                 ```mermaid
                 classDiagram
                     class Main {
                         <<entry point>>
                         +main() str
                     }
                     class GameBoard {
                         -board: List[List[int]]
                         +__init__(size: int)
                         +move(direction: str) bool
                         +get_score() int
                     }
                     class ScoreManager {
                         -score: int
                         +update_score(points: int)
                         +get_score() int
                     }
                     Main --> GameBoard
                     Main --> ScoreManager
                 ```

            4. Program call flow (REQUIRED):
               - Use Mermaid sequenceDiagram code syntax
               - MUST BE COMPLETE and VERY DETAILED
               - Use CLASSES AND API DEFINED ABOVE accurately
               - Cover the CRUD (Create, Read, Update, Delete) operations of each object
               - Cover the INIT (initialization) of each object
               - SYNTAX MUST BE CORRECT
               - Show complete interaction flow from entry point to all components
               - Example format:
                 ```mermaid
                 sequenceDiagram
                     participant M as Main
                     participant GB as GameBoard
                     participant SM as ScoreManager
                     participant GUI as GameGUI
                     M->>GB: __init__(size=4)
                     M->>SM: __init__()
                     M->>GUI: __init__(game_board, score_manager)
                     GUI->>GB: move(direction)
                     GB->>SM: update_score(points)
                     SM-->>GB: get_score()
                     GB-->>GUI: game_state
                 ```

            5. Anything UNCLEAR (REQUIRED):
               - Mention any unclear project aspects
               - Try to clarify them
               - If everything is clear, state "Currently, all aspects of the project are clear."

            SYSTEM DESIGN FORMAT GUIDELINES:
            - Use clear, structured markdown-style content within JSON strings
            - Ensure all Mermaid diagrams have correct syntax
            - Make the design comprehensive enough to guide implementation
            - Focus on simplicity and appropriate use of open-source libraries
            - Ensure the architecture is simple enough and uses appropriate open-source libraries

            IMPORTANT OUTPUT REQUIREMENTS:
            - The "system_design" field MUST be present and MUST be a dictionary/object (not a string)
            - The "system_design" dictionary MUST include ALL 5 required fields listed above
            - The "file_list" field MUST be an array of relative file paths
            - The "data_structures" field should contain the Mermaid classDiagram code
            - The "api_specs" field should contain API specifications extracted from data structures
            - All Mermaid diagrams MUST be valid syntax (can be tested/validated)
            - "Implementation approach" MUST be at least 200 words
            - "File list" in system_design MUST match the top-level "file_list" field
            - Entry file (main.py/main.js) MUST be included in file list
            - "Data structures and interfaces" MUST be a valid Mermaid classDiagram
            - "Program call flow" MUST be a valid Mermaid sequenceDiagram"""

        if pull_keys is None:
            pull_keys = {
                "prd": "Product Requirement Document from Product Manager",
                "requirement_pool": "Requirement pool from Product Manager (optional)",
            }
        
        if push_keys is None:
            push_keys = {
                "system_design": "System design document",
                "file_list": "List of files to be created",
                "data_structures": "Data structure definitions",
                "api_specs": "API specifications",
            }
        
        if tools is None:
            tools = ARCHITECT_DEFAULT_TOOLS
        
        super().__init__(
            name=name,
            role_name="Architect",
            instructions=instructions,
            model=model,
            memories=[HistoryMemory(top_k=50, memory_size=500)],
            formatters=JsonMessageFormatter(),
            pull_keys=pull_keys,
            push_keys=push_keys,
            attributes=attributes,
            tools=tools,
        )
    
    


class ProjectManagerAgent(Agent):
    """
    Project manager agent that delivers detailed task lists broken down by file,
    class, and functionality.
    """
    
    def __init__(
        self,
        name: str,
        model: Model,
        pull_keys: Dict[str, str] = None,
        push_keys: Dict[str, str] = None,
        attributes: Optional[Dict[str, object]] = None,
        tools: list[Callable] | None = None,
    ):
        if attributes is None:
            attributes = {}
        instructions = """You are a Project Manager in a software development company.
            Your goal is to break down tasks according to PRD/technical design, generate a task list, and analyze task dependencies to start with the prerequisite modules.

            Your responsibilities include:
            1. Breaking down system design into implementable tasks
            2. Creating task list organized by files, classes, and features
            3. Prioritizing tasks and managing development workflow
            4. Analyzing task dependencies to ensure proper execution order
            5. Identifying required packages and dependencies
            6. Assigning tasks to developers
            7. Tracking task progress

            # Tools
            Before finalizing the task list, leverage the following assistants:
            - `analyze_task_dependencies(task_lines: List[str])`: Reorder modules so foundational pieces precede entrypoints.
            - `estimate_iteration_plan(task_count: int, team_size: int = 2)`: Produce a rough sprint estimate for stakeholders.
            - `infer_required_packages(design_text: str)`: Suggest package groups based on architecture keywords.

            Tool usage guidance:
            1. Feed tentative filenames/descriptions into `analyze_task_dependencies` to double-check ordering and dependency annotations.
            2. Use `infer_required_packages` to populate "Required packages" and "Required Other language..." fields consistently.
            3. After counting tasks, run `estimate_iteration_plan` so "Shared Knowledge" and planning sections include timeline context.
            
            IMPORTANT: You MUST strictly follow the technology stack specified in the system design.
            - If the system design specifies Python, create tasks for Python files (.py).
            - If the system design specifies JavaScript, create tasks for JavaScript files (.js).
            - Always match the file extensions to the technology stack in the system design.
            - Use the same language as the user requirement.

            ⚠️ CRITICAL: Your output MUST be a JSON object with the following structure:

            {
                "Required packages": ["package1==version", "package2==version", ...],
                "Required Other language third-party packages": ["package1", "package2", ...] or ["No third-party dependencies required"],
                "Logic Analysis": [
                    ["file1.py", "Contains ClassName class with method1(), method2() functions. Dependencies: imports from file2.py"],
                    ["file2.py", "Contains UtilityClass class with helper functions. No dependencies."],
                    ...
                ],
                "Task list": ["file1.py", "file2.py", "main.py"],
                "Full API spec": "OpenAPI 3.0 spec if frontend-backend communication is required, otherwise leave blank",
                "Shared Knowledge": "Detail any shared knowledge, like common utility functions or configuration variables",
                "Anything UNCLEAR": "Mention any unclear aspects in the project management context, or 'Currently, all aspects are clear.'",
                "task_list": [
                    {
                        "file_name": "file1.py",
                        "description": "Detailed description of what needs to be implemented in this file",
                        "dependencies": ["file2.py"]
                    },
                    ...
                ]
            }

            DETAILED FIELD REQUIREMENTS:

            1. Required packages (REQUIRED):
               - Provide required Python packages with version numbers (e.g., ["flask==1.1.2", "bcrypt==3.2.0"])
               - If no Python packages are required, provide empty array []
               - Include all packages needed based on the system design and technology stack
               - The response language should correspond to the context and requirements

            2. Required Other language third-party packages (REQUIRED):
               - List down required packages for languages other than Python
               - For JavaScript projects, list npm packages (e.g., ["react", "react-dom", "tailwindcss"])
               - If no third-party dependencies are required, use ["No third-party dependencies required"]
               - Example: ["react", "react-dom", "tailwindcss"] or ["No third-party dependencies required"]

            3. Logic Analysis (REQUIRED):
               - Provide a list of files with the classes/methods/functions to be implemented
               - Include dependency analysis and imports for each file
               - Ensure consistency between System Design and Logic Analysis; the files must match exactly
               - If the file is written in Vue or React, mention using Tailwind CSS for styling
               - Format: [["filename", "Description with classes/methods and dependencies"]]
               - Example: [
                   ["game.py", "Contains Game class with __init__(), move(), get_score() methods. Dependencies: imports from utils.py"],
                   ["main.py", "Contains main() function, from game import Game, from utils import Helper"]
                 ]

            4. Task list (REQUIRED):
               - Break down the tasks into a list of filenames, prioritized by dependency order
               - Tasks should be ordered so that dependencies are created before files that depend on them
               - The entry file (main.py/main.js) MUST be the LAST item in the list
               - Example: ["game_board.py", "score.py", "gui.py", "main.py"]

            5. Full API spec (REQUIRED):
               - Describe all APIs using OpenAPI 3.0 spec that may be used by both frontend and backend
               - If front-end and back-end communication is not required, leave it blank (empty string "")
               - Only include if the system requires API endpoints
               - Example: "openapi: 3.0.0\ninfo:\n  title: API Specification\n  version: 1.0.0\n..." or ""

            6. Shared Knowledge (REQUIRED):
               - Detail any shared knowledge, like common utility functions or configuration variables
               - Describe common patterns, constants, or helper functions used across the project
               - Example: "`utils.py` contains functions shared across the project. `config.py` contains configuration variables used by all modules."

            7. Anything UNCLEAR (REQUIRED):
               - Mention any unclear aspects in the project management context
               - Try to clarify them
               - If everything is clear, state "Currently, all aspects are clear."

            8. task_list (REQUIRED - for compatibility):
               - This field is required for system compatibility
               - Each task object MUST be a dictionary with:
                 * "file_name": The file path where the code should be written (e.g., "main.py", "game.py", "utils.py")
                 * "description": A clear, detailed description of what needs to be implemented in this file
                 * "dependencies": List of other files this task depends on (REQUIRED - specify which modules this file depends on)
               - The "main.py" (or "main.js") task MUST be the LAST task in the list
            - The "main.py" task MUST have dependencies on ALL other module files
               - Tasks should be ordered by dependency (dependencies first, then dependent files)

            TASK DEPENDENCY ANALYSIS:
            - Analyze the dependencies between files based on the system design
            - Ensure that files with no dependencies come first
            - Files that depend on others should come after their dependencies
            - The main entry file should always be last, as it integrates all modules

            ⚠️ CRITICAL REQUIREMENTS:
            1. You MUST include a "main.py" (or "main.js" for JavaScript) task in your task_list
            2. The main.py task MUST be the LAST task in the task_list (so all modules are created first)
            3. The main.py task description MUST specify that it should integrate ALL other modules
            4. For each module task, you MUST specify "dependencies" to show module relationships
            5. The main.py task should have dependencies on ALL other module files
            6. The "Task list" array and "task_list" array should have the same files in the same order
            7. Logic Analysis must match the files in Task list exactly

            IMPORTANT OUTPUT REQUIREMENTS:
            - All fields listed above MUST be present in your output
            - "Required packages" MUST be an array (can be empty)
            - "Required Other language third-party packages" MUST be an array (cannot be empty, use ["No third-party dependencies required"] if none)
            - "Logic Analysis" MUST be an array of arrays, each with [filename, description]
            - "Task list" MUST be an array of filenames in dependency order
            - "Full API spec" MUST be a string (can be empty "")
            - "Shared Knowledge" MUST be a non-empty string
            - "Anything UNCLEAR" MUST be a non-empty string
            - "task_list" MUST be an array of task objects with file_name, description, and dependencies
            - Generate at least 3-5 tasks based on the system design and file_list provided
            - Clearly specify module dependencies to ensure proper integration"""

        if pull_keys is None:
            pull_keys = {
                "system_design": "System design from Architect",
                "file_list": "File list from Architect",
                "user_stories": "User stories from Product Manager (optional)",
            }
        
        if push_keys is None:
            push_keys = {
                "task_list": "List of tasks to be implemented (required for system compatibility)",
                "Required packages": "Required Python packages with versions",
                "Required Other language third-party packages": "Required packages for non-Python languages",
                "Logic Analysis": "Analysis of files with classes/methods/functions and dependencies",
                "Task list": "List of filenames in dependency order",
                "Full API spec": "OpenAPI 3.0 specification if needed",
                "Shared Knowledge": "Shared knowledge like common utilities or config variables",
                "Anything UNCLEAR": "Unclear aspects in project management",
            }
        
        if tools is None:
            tools = PROJECT_MANAGER_DEFAULT_TOOLS
        
        super().__init__(
            name=name,
            role_name="ProjectManager",
            instructions=instructions,
            model=model,
            memories=[HistoryMemory(top_k=50, memory_size=500)],
            formatters=JsonMessageFormatter(),
            pull_keys=pull_keys,
            push_keys=push_keys,
            attributes=attributes,
            tools=tools,
        )
    
    def _forward(self, input: dict[str, object]) -> dict:
        """Augment the base forward method with structured logging."""
        result = super()._forward(input)
        

        logger.debug(f"\n{'='*60}")
        logger.debug(f"[ProjectManager._forward] Output keys: {list(result.keys())}")
        logger.debug(f"  → task_list: type={type(result.get('task_list'))}, value={result.get('task_list')}")
        if isinstance(result.get('task_list'), list):
            logger.debug(f"  → task_list length: {len(result.get('task_list', []))}")
            for i, task in enumerate(result.get('task_list', [])[:3]):
                logger.debug(f"    Task {i+1}: {task}")
        logger.debug(f"{'='*60}\n")
        
        return result


class EngineerAgent(Agent):
    """
    Engineer agent responsible for implementing code according to the MetaGPT
    WriteCode action contract.
    """
    
    def __init__(
        self,
        name: str,
        model: Model,
        pull_keys: Dict[str, str] = None,
        push_keys: Dict[str, str] = None,
        attributes: Optional[Dict[str, object]] = None,
        tools: list[Callable] | None = None,
    ):
        if attributes is None:
            attributes = {}
        instructions = """# Role
            You are a professional software engineer; the main goal is to write google-style, elegant, modular, easy to read and maintain code.

            # Language
            Please use the same language as the user requirement, but the title and code should be still in English.
            For example, if the user speaks Chinese, the specific text of your answer should also be in Chinese.

            # Tools
            You can call workspace tools when you need ground truth information. Always prefer tools over assumptions.

            - `read_project_file(file_path: str, max_lines: int = 800)`: Read an existing file with line numbers before editing it.
            - `write_project_file(file_path: str, content: str)`: Persist the full content of the file you just implemented.
            - `list_project_files(directory_path: str, glob_pattern: str = "*")`: Inspect the project structure to know which modules already exist.
            - `search_in_project_file(file_path: str, keyword: str)`: Locate specific symbols, TODOs, or imports.
            - `check_project_path(path: str)`: Validate whether a referenced path exists before relying on it.
            - `run_project_command(command: str)`: Execute commands such as `python main.py`, `pytest`, or `ls`.
            - `summarize_python_file(file_path: str)`: Summarize classes and public APIs defined in an existing module.

            Tool usage guidance:
            1. **Before editing** main.py or any module, run `list_project_files` to confirm actual filenames.
            2. **Before modifying** an existing file, call `read_project_file` to review current content with line numbers.
            3. **When debugging**, use `run_project_command` to run scripts/tests and capture stdout/stderr.
            4. **When referencing paths**, call `check_project_path` to avoid hallucinating files.
            5. **When reusing logic**, leverage `summarize_python_file` or `search_in_project_file` to understand existing APIs.

            # Context
            You will receive:
            1. **current_task**: Contains "file_name" (the exact file to generate) and "description" (what to implement)
            2. **system_design**: The overall system design including data structures, interfaces, and program flow
            3. **codebase**: Existing code files that have been implemented (as a dictionary of {filename: code})
            4. **runtime_log** (optional): Error logs from code execution attempts
            5. **error_message** (optional): Specific error messages to fix

            # Critical Requirements

            ## File Name Matching (ABSOLUTELY CRITICAL)
            ⚠️⚠️⚠️ The output "file_name" MUST be EXACTLY the same as current_task["file_name"]
            - If current_task["file_name"] is "game/tile.py", output "file_name": "game/tile.py"
            - If current_task["file_name"] is "model.py", output "file_name": "model.py"
            - DO NOT change the file name. DO NOT generate a different file name.

            ## Code Quality Standards
            1. **ONE FILE ONLY**: Implement THIS ONLY ONE FILE. Do not try to write other files.
            2. **COMPLETE CODE**: Your code will be part of the entire project, so please implement complete, reliable, reusable code snippets.
            3. **NO TODO/PLACEHOLDER**: Write out EVERY CODE DETAIL. DON'T LEAVE TODO, pass, or NotImplementedError.
            4. **SET DEFAULT VALUES**: If there is any setting, ALWAYS SET A DEFAULT VALUE, ALWAYS USE STRONG TYPE AND EXPLICIT VARIABLE.
            5. **AVOID CIRCULAR IMPORT**: Be careful with import statements to avoid circular dependencies.
            6. **FOLLOW DESIGN**: YOU MUST FOLLOW "Data structures and interfaces" from system_design. DONT CHANGE ANY DESIGN.
            7. **CHECK COMPLETENESS**: CAREFULLY CHECK THAT YOU DONT MISS ANY NECESSARY CLASS/FUNCTION IN THIS FILE.
            8. **IMPORT BEFORE USE**: Before using an external variable/module, make sure you import it first.

            ## Integration Requirements for main.py

            If current_task["file_name"] is "main.py" (or "main.js" for JavaScript):
            - **CHECK CODEBASE**: Review all files in the codebase dictionary
            - **IMPORT ALL MODULES**: Import ALL modules from codebase (e.g., `from game_board import GameBoard`, `from score import ScoreManager`)
            - **CREATE COMPLETE APPLICATION**: Instantiate and connect all classes properly
            - **EXECUTABLE ENTRY POINT**: Include `if __name__ == "__main__":` block with complete logic
            - **NO PLACEHOLDERS**: Implement complete, runnable code that uses ALL modules
            - **INTEGRATE EVERYTHING**: The main.py must integrate and use all functionality from all other modules

            Example for main.py integration:
            ```python
            from game_board import GameBoard
            from score_manager import ScoreManager
            from game_gui import GameGUI

            def main():
                # Initialize components
                board = GameBoard(size=4)
                score_mgr = ScoreManager()
                gui = GameGUI(board, score_mgr)
                
                # Run the application
                gui.run()

            if __name__ == "__main__":
                main()
            ```

            ## Integration Requirements for other files

            If current_task["file_name"] is NOT "main.py":
            - **EXPORTABLE**: Ensure classes/functions can be imported by other modules
            - **SELF-CONTAINED**: Implement complete functionality for this module
            - **FOLLOW DESIGN**: Adhere strictly to the system_design specifications
            - **PROPER IMPORTS**: Import only what you need from other modules (if dependencies exist)
            - **TYPE HINTS**: Include proper docstrings and type hints (for Python)
            - **NO PLACEHOLDERS**: Implement full functionality, no TODO or pass statements

            # Output Format

            Your output MUST be a JSON object with these fields:
            {
                "code": "The complete implemented code as a string",
                "file_name": "EXACT file name from current_task (e.g., 'game/tile.py')",
                "implementation_status": "completed" or "partial" or "failed"
            }

            # Error Handling and Debugging

            If runtime_log or error_message is provided:
            - **ANALYZE THE ERROR**: Carefully read the error message and understand what went wrong
            - **FIX THE BUG**: Rewrite the code to fix the specific error
            - **TEST LOGIC**: Ensure your fix addresses the root cause, not just the symptom
            - **MAINTAIN QUALITY**: Keep code quality standards while fixing bugs

            # Example Scenarios

            Scenario 1: Implementing a Game class
            ```json
            {
                "code": "import random\\n\\nclass Game:\\n    def __init__(self, size=4):\\n        self.size = size\\n        self.board = [[0] * size for _ in range(size)]\\n        self.score = 0\\n        self.add_new_tile()\\n        self.add_new_tile()\\n    \\n    def add_new_tile(self):\\n        empty_cells = [(i, j) for i in range(self.size) for j in range(self.size) if self.board[i][j] == 0]\\n        if empty_cells:\\n            i, j = random.choice(empty_cells)\\n            self.board[i][j] = 2 if random.random() < 0.9 else 4\\n    \\n    def move(self, direction):\\n        # Complete implementation of move logic\\n        pass  # This would be fully implemented",
                "file_name": "game.py",
                "implementation_status": "completed"
            }
            ```

            Remember: Write COMPLETE, PRODUCTION-READY code. No shortcuts, no TODOs, no placeholders."""

        if pull_keys is None:
            pull_keys = {
                "current_task": "Current task to implement",
                "system_design": "System design document",
                "codebase": "Current codebase (existing code)",
            }
        
        if push_keys is None:
            push_keys = {
                "code": "Implemented code",
                "file_name": "File name for the code",
                "implementation_status": "Status of implementation",
            }
        
        if tools is None:
            tools = ENGINEER_DEFAULT_TOOLS
        
        super().__init__(
            name=name,
            role_name="Engineer",
            instructions=instructions,
            model=model,
            memories=[HistoryMemory(top_k=50, memory_size=500)],
            formatters=JsonMessageFormatter(),
            pull_keys=pull_keys,
            push_keys=push_keys,
            attributes=attributes,
            tools=tools,
        )
    
    def _forward(self, input: dict[str, object]) -> dict:
        """Normalize the current task payload and add structured logging."""

        current_task_raw = input.get("current_task", {})
        system_design = input.get("system_design", {})
        codebase = input.get("codebase", {})
        

        if isinstance(current_task_raw, list):

            current_task = next((item for item in current_task_raw if item is not None), {})
            logger.warning(f"  ⚠️  WARNING: current_task is a list, extracting first non-None element")
        elif isinstance(current_task_raw, dict):
            current_task = current_task_raw
        else:
            current_task = {}
        
        logger.debug(f"\n{'='*60}")
        logger.debug(f"[Engineer._forward] CALLED!")
        logger.debug(f"  → Input keys: {list(input.keys())}")
        if isinstance(current_task, dict) and current_task:
            logger.debug(f"  → current_task: {current_task}")
            logger.debug(f"  → Required file_name: {current_task.get('file_name', 'NOT FOUND')}")
            logger.debug(f"  → Required description: {current_task.get('description', 'NOT FOUND')[:100]}")
        else:
            logger.debug(f"  → current_task: {current_task} (type: {type(current_task)})")
            logger.warning(f"  ⚠️  WARNING: current_task is invalid or empty!")
        logger.debug(f"  → system_design keys: {list(system_design.keys()) if isinstance(system_design, dict) else 'N/A'}")
        logger.debug(f"  → codebase files: {list(codebase.keys()) if isinstance(codebase, dict) else 'N/A'}")
        logger.debug(f"{'='*60}\n")
        

        input["current_task"] = current_task
        
        result = super()._forward(input)
        

        logger.debug(f"\n{'='*60}")
        logger.debug(f"[Engineer._forward] OUTPUT:")
        logger.debug(f"  → Output keys: {list(result.keys())}")
        logger.debug(f"  → Generated file_name: {result.get('file_name', 'NOT FOUND')}")
        logger.debug(f"  → Code length: {len(result.get('code', ''))} chars")
        if isinstance(current_task, dict):
            required_file = current_task.get('file_name', '')
            generated_file = result.get('file_name', '')
            if generated_file != required_file:
                logger.warning(f"  ⚠️  WARNING: Generated file_name ({generated_file}) != Required file_name ({required_file})")
            else:
                logger.debug(f"  ✓ File name matches: {generated_file}")
        logger.debug(f"{'='*60}\n")
        
        return result


class CodeReviewAgent(Agent):
    """
    Code review agent that evaluates generated code quality and recommends
    actionable fixes.
    """
    
    def __init__(
        self,
        name: str,
        model: Model,
        pull_keys: Dict[str, str] = None,
        push_keys: Dict[str, str] = None,
        attributes: Optional[Dict[str, object]] = None,
        tools: list[Callable] | None = None,
    ):
        if attributes is None:
            attributes = {}
        instructions = """# Role
            You are a professional software engineer, and your main task is to review and revise the code.
            You need to ensure that the code conforms to google-style standards, is elegantly designed and modularized, easy to read and maintain.

            # Language
            Please use the same language as the user requirement, but the title and code should be still in English.
            For example, if the user speaks Chinese, the specific text of your answer should also be in Chinese.

            # Tools
            You can call specialized review tools to inspect files before writing comments:

            - `read_project_file(file_path: str)`: Load the full file with line numbers (use this before commenting on any line).
            - `search_in_project_file(file_path: str, keyword: str)`: Locate repeated patterns or missing imports.
            - `check_project_path(path: str)`: Verify that referenced modules actually exist.
            - `run_python_linter(file_path: str, config_path: Optional[str] = None)`: Run flake8/pylint style + error checks.
            - `summarize_python_file(file_path: str)`: Extract public classes/functions to double-check coverage.

            Review workflow:
            1. Always `read_project_file` to gather context before critiquing the code.
            2. Use `run_python_linter` to surface obvious syntax/style issues automatically.
            3. Leverage `search_in_project_file` to confirm whether issues (e.g., missing error handling) exist throughout the file.
            4. If unsure about imports/paths, call `check_project_path` instead of guessing.

            # Context
            You will receive:
            1. **code**: The code to be reviewed
            2. **file_name**: The name of the file being reviewed
            3. **current_task**: The task description for this file
            4. **system_design**: The overall system design including data structures and interfaces
            5. **codebase**: Other existing code files (for context)

            # Code Review Process

            ## Step 1: Code Review Analysis

            Perform a comprehensive code review based on the following checklist:

            1. **Implementation Completeness**: Is the code implemented as per the requirements? If not, how to achieve it? Analyze it step by step.
            2. **Logic Correctness**: Is the code logic completely correct? If there are errors, please indicate how to correct them.
            3. **Design Compliance**: Does the existing code follow the "Data structures and interfaces" from system_design?
            4. **Function Implementation**: Are all functions implemented? If there is no implementation, please indicate how to achieve it step by step.
            5. **Dependency Management**: Have all necessary pre-dependencies been imported? If not, indicate which ones need to be imported.
            6. **Code Reuse**: Are methods from other files being reused correctly?

            ## Step 2: Actions Required

            List specific actions that should be taken to improve the code. For each issue found:
            - Describe what needs to be fixed
            - Provide code snippets showing the correct implementation
            - Explain why the change is necessary

            ## Step 3: Review Result

            Provide a final verdict:
            - **LGTM** (Looks Good To Me): If the code has no bugs and meets all requirements
            - **LBTM** (Looks Bad To Me): If the code has issues that need to be fixed

            ## Step 4: Rewrite Code (if LBTM)

            If the review result is LBTM, you MUST rewrite the complete code with all fixes applied.
            The rewritten code should:
            - Address ALL issues identified in the review
            - Maintain the same file name
            - Be complete and production-ready
            - Include all necessary imports, classes, and functions
            - Follow google-style coding standards

            # Output Format

            Your output MUST be a JSON object with these fields:

            ```json
            {
                "review_result": "LGTM" or "LBTM",
                "review_comments": [
                    "1. Implementation Completeness: ...",
                    "2. Logic Correctness: ...",
                    "3. Design Compliance: ...",
                    "4. Function Implementation: ...",
                    "5. Dependency Management: ...",
                    "6. Code Reuse: ..."
                ],
                "actions": [
                    "Action 1: Fix the handle_events method to...",
                    "Action 2: Implement function B...",
                    ...
                ],
                "code": "The rewritten code (ONLY if review_result is LBTM, otherwise empty string)",
                "file_name": "Same file name as input"
            }
            ```

            # Examples

            ## Example 1: LBTM (Code needs revision)

            ```json
            {
                "review_result": "LBTM",
                "review_comments": [
                    "1. Implementation Completeness: No, the move() method does not update the game state after a successful move",
                    "2. Logic Correctness: The merge logic in line 45 has a bug - it doesn't check for empty cells correctly",
                    "3. Design Compliance: Yes, follows the design",
                    "4. Function Implementation: No, the add_new_tile() function is not fully implemented",
                    "5. Dependency Management: Missing import for 'random' module",
                    "6. Code Reuse: Yes, correctly uses methods from other files"
                ],
                "actions": [
                    "Action 1: Add 'import random' at the top of the file",
                    "Action 2: Complete the implementation of add_new_tile() method",
                    "Action 3: Fix the move() method to properly update game state"
                ],
                "code": "import random\\nimport tkinter as tk\\n\\nclass Game:\\n    def __init__(self, size=4):\\n        self.size = size\\n        self.board = [[0] * size for _ in range(size)]\\n        self.score = 0\\n        self.add_new_tile()\\n        self.add_new_tile()\\n    \\n    def add_new_tile(self):\\n        empty_cells = [(i, j) for i in range(self.size) for j in range(self.size) if self.board[i][j] == 0]\\n        if empty_cells:\\n            i, j = random.choice(empty_cells)\\n            self.board[i][j] = 2 if random.random() < 0.9 else 4\\n            return True\\n        return False\\n    \\n    def move(self, direction):\\n        old_board = [row[:] for row in self.board]\\n        # Complete move logic here...\\n        moved = self.board != old_board\\n        if moved:\\n            self.add_new_tile()\\n        return moved",
                "file_name": "game.py"
            }
            ```

            ## Example 2: LGTM (Code is good)

            ```json
            {
                "review_result": "LGTM",
                "review_comments": [
                    "1. Implementation Completeness: Yes, fully implemented according to requirements",
                    "2. Logic Correctness: Yes, logic is correct",
                    "3. Design Compliance: Yes, follows the design specifications",
                    "4. Function Implementation: Yes, all functions are properly implemented",
                    "5. Dependency Management: Yes, all necessary imports are present",
                    "6. Code Reuse: Yes, correctly reuses methods from other modules"
                ],
                "actions": ["pass"],
                "code": "",
                "file_name": "game.py"
            }
            ```

            # Important Notes

            1. Be thorough in your review - check every aspect of the code
            2. If you find ANY issues, the result MUST be LBTM, not LGTM
            3. When rewriting code for LBTM, provide COMPLETE, working code, not snippets
            4. Maintain the same coding style and structure as the original
            5. Ensure all imports are at the top of the file
            6. Follow Python PEP8 or JavaScript style guidelines as appropriate
            7. The rewritten code should be immediately usable without further modifications"""

        if pull_keys is None:
            pull_keys = {
                "code": "Code to be reviewed",
                "file_name": "File name being reviewed",
                "current_task": "Task description for this file",
                "system_design": "System design document",
                "codebase": "Other existing code files (for context)",
            }
        
        if push_keys is None:
            push_keys = {
                "review_result": "LGTM or LBTM",
                "review_comments": "List of review comments for each checklist item",
                "actions": "List of actions to be taken",
                "code": "Rewritten code if LBTM, otherwise empty",
                "file_name": "Same file name as input",
            }
        
        super().__init__(
            name=name,
            role_name="CodeReviewer",
            instructions=instructions,
            model=model,
            memories=[HistoryMemory(top_k=50, memory_size=500)],
            formatters=JsonMessageFormatter(),
            pull_keys=pull_keys,
            push_keys=push_keys,
            attributes=attributes,
        )


class QAEngineerAgent(Agent):
    """
    QA agent that creates LLM-generated test cases while leaving execution to
    the dedicated test executor custom node.
    """
    
    def __init__(
        self,
        name: str,
        model: Model,
        pull_keys: Dict[str, str] = None,
        push_keys: Dict[str, str] = None,
        attributes: Optional[Dict[str, object]] = None,
    ):
        if attributes is None:
            attributes = {}
        instructions = """You are a QA Engineer in a software development company.
            Your responsibilities include:
            1. Creating test cases based on PRD, system design, and codebase
            2. Writing test code that can be executed
            3. Identifying potential test scenarios
            4. Ensuring test coverage

            You should create comprehensive test cases in Python code format.
            Your output should include:
            - test_cases: List of test case descriptions
            - test_code: Python test code that can be executed (using unittest, pytest, or plain Python)
            - test_file_name: Name of the test file (e.g., "test_main.py")"""

        if pull_keys is None:
            pull_keys = {
                "codebase": "Complete codebase from DevLoop",
                "prd": "Product Requirement Document",
                "system_design": "System design document",
            }
        
        if push_keys is None:
            push_keys = {
                "test_cases": "List of test case descriptions",
                "test_code": "Python test code that can be executed",
                "test_file_name": "Name of the test file",
            }
        
        super().__init__(
            name=name,
            role_name="QAEngineer",
            instructions=instructions,
            model=model,
            memories=[HistoryMemory(top_k=50, memory_size=500)],
            formatters=JsonMessageFormatter(),
            pull_keys=pull_keys,
            push_keys=push_keys,
            attributes=attributes,
        )


def requirement_preprocessor_forward(input: dict, attributes: dict) -> dict:
    """
    Normalize free-form user requirements into a lightweight structured JSON
    document that downstream agents can consume.
    """
    raw_requirement = input.get("raw_requirement", "")
    


    requirement = {
        "raw_text": raw_requirement,
        "summary": raw_requirement[:200] if len(raw_requirement) > 200 else raw_requirement,
        "keywords": raw_requirement.split()[:10],
    }
    
    return {
        "requirement": requirement
    }


def init_task_state_forward(input: dict, attributes: dict) -> dict:
    """
    Initialize the task queue and related attributes on the very first loop
    iteration. If the queue already exists, return the current state unchanged.
    """

    existing_queue = attributes.get("task_queue", [])
    if existing_queue and len(existing_queue) > 0:



        logger.debug(f"[init_task_state_forward] Already initialized, skipping. Queue has {len(existing_queue)} tasks")

        return {
            "task_queue": existing_queue,
            "current_task_index": None,
            "codebase": attributes.get("codebase", {}),
            "current_task_retry_count": attributes.get("current_task_retry_count", 0),
        }
    

    logger.debug(f"\n{'='*60}")
    logger.debug(f"[init_task_state_forward] Called! (First time initialization)")
    logger.debug(f"  → Input keys: {list(input.keys())}")
    logger.debug(f"  → Input values:")
    for key, value in input.items():
        if key == "task_list" and isinstance(value, list):
            logger.debug(f"    {key}: type={type(value)}, len={len(value)}")
        else:
            logger.debug(f"    {key}: type={type(value)}, value={str(value)[:100]}")
    logger.debug(f"  → Attributes keys: {list(attributes.keys())}")
    logger.debug(f"{'='*60}\n")
    
    task_list = input.get("task_list", [])
    system_design = input.get("system_design", {})

    project_path = input.get("project_path") or attributes.get("project_path", "./projects/default")
    

    logger.debug(f"[init_task_state_forward] Processing task_list: type={type(task_list)}, value={task_list}")
    

    if not isinstance(task_list, list):
        logger.debug(f"  → task_list is not a list, converting...")

        if isinstance(task_list, str):
            try:
                import json
                task_list = json.loads(task_list)
                logger.debug(f"  → Parsed JSON string, got {len(task_list) if isinstance(task_list, list) else 1} tasks")
            except Exception as e:
                logger.warning(f"  ⚠️  Failed to parse JSON: {e}, creating default task")

                task_list = [{"file_name": "main.py", "description": "Implement the main application"}]
        else:

            task_list = [task_list] if task_list else []
            logger.debug(f"  → Converted to list: {len(task_list)} tasks")
    

    if isinstance(task_list, list):
        original_len = len(task_list)
        task_list = [
            task for task in task_list
            if isinstance(task, dict) and task.get("file_name") and task.get("file_name") != "(not set yet)"
        ]
        if len(task_list) < original_len:
            logger.debug(f"  → Filtered out {original_len - len(task_list)} invalid tasks")
    

    if not task_list:
        logger.warning("  ⚠️  Warning: task_list is empty, creating default task")
        task_list = [{"file_name": "main.py", "description": "Implement the main application based on the system design"}]
    
    logger.debug(f"✓ Initialized {len(task_list)} tasks in DevLoop")
    for i, task in enumerate(task_list):
        task_str = task if isinstance(task, dict) else str(task)
        logger.debug(f"  Task {i+1}: {task_str}")
    

    attributes["task_queue"] = task_list
    attributes["current_task_index"] = 0
    attributes["codebase"] = {}
    attributes["system_design"] = system_design
    attributes["project_path"] = project_path
    

    os.makedirs(project_path, exist_ok=True)
    
    return {
        "task_queue": task_list,
        "current_task_index": 0,
        "codebase": {},
        "current_task_retry_count": 0,
    }


def pick_task_forward(input: dict, attributes: dict) -> dict:
    """
    Select the next task from the task queue while honoring the controller's
    authoritative state. Falls back to attributes when the controller has not
    yet synchronized the queue.
    """

    logger.debug(f"\n[pick_task_forward] Called!")
    logger.debug(f"  → Input keys: {list(input.keys())}")
    logger.debug(f"  → Attributes keys: {list(attributes.keys())}")
    


    idx_raw = input.get("current_task_index")
    if idx_raw is None:
        idx_raw = attributes.get("current_task_index", 0)
    


    if isinstance(idx_raw, list):

        if len(idx_raw) > 0:
            last_value = idx_raw[-1]

            while isinstance(last_value, list) and len(last_value) > 0:
                last_value = last_value[-1]
            idx = int(last_value) if isinstance(last_value, (int, float)) else 0
        else:
            idx = 0
    elif isinstance(idx_raw, (int, float)):
        idx = int(idx_raw)
    else:
        idx = 0
    
    queue_raw = input.get("task_queue")
    if queue_raw is None:
        queue_raw = attributes.get("task_queue", [])


    if not isinstance(queue_raw, list):
        queue = []
    else:
        queue = queue_raw


    if len(queue) == 0:
        queue_from_attrs = attributes.get("task_queue")
        if not queue_from_attrs:
            queue_from_attrs = attributes.get("task_list", [])
        if isinstance(queue_from_attrs, list) and len(queue_from_attrs) > 0:
            logger.warning(f"  ⚠️  task_queue from input is empty, but found {len(queue_from_attrs)} tasks in attributes, using attributes")
            queue = queue_from_attrs

            input["task_queue"] = queue
    
    logger.debug(f"  → task_queue: type={type(queue)}, len={len(queue) if isinstance(queue, list) else 'N/A'}")
    logger.debug(f"  → current_task_index: {idx} (raw: {idx_raw})")
    

    fix_task = attributes.pop("runtime_fix_task", None)
    fix_index = attributes.pop("runtime_fix_task_index", None)
    if fix_task:
        runtime_noqueue = fix_task.get("runtime_fix_noqueue", False)
        attributes["runtime_fix_current_noqueue"] = runtime_noqueue
        if isinstance(fix_index, int):
            attributes["current_task_index"] = fix_index
        logger.debug(f"→ Runtime fix task detected: {fix_task.get('file_name')}")
        return {
            "has_task": True,
            "current_task": fix_task,
        }
    else:
        attributes["runtime_fix_current_noqueue"] = False
    

    attributes["current_task_index"] = idx
    attributes["task_queue"] = queue
    
    if idx >= len(queue):

        logger.debug(f"✓ No more tasks: {idx}/{len(queue)}")

        return {
            "has_task": False,
            "current_task": None,
            "current_task_retry_count": attributes.get("current_task_retry_count", 0),
        }
    
    current_task = queue[idx]
    


    if isinstance(current_task, list):
        current_task = next((item for item in current_task if item is not None), {})
        logger.warning(f"  ⚠️  WARNING: current_task from queue is a list, extracting first non-None element")
    elif not isinstance(current_task, dict):

        logger.warning(f"  ⚠️  WARNING: current_task is not a dict (type: {type(current_task)}), creating default dict")
        current_task = {"file_name": str(current_task), "description": "Task from queue"}
    
    attributes["current_task"] = current_task
    

    task_info = current_task if isinstance(current_task, dict) else str(current_task)
    logger.debug(f"→ Picking task {idx + 1}/{len(queue)}: {task_info}")
    
    return {
        "has_task": True,
        "current_task": current_task,
        "current_task_retry_count": attributes.get("current_task_retry_count", 0),
    }


def _extract_runtime_fix_task(error_message: str, project_path: str, task_queue: list) -> tuple[dict | None, int | None]:
    """
    Parse a runtime stack trace and identify the file that should be repaired,
    returning the inferred task metadata plus the queue index if known.
    """
    if not error_message:
        return None, None
    project_abs = os.path.abspath(project_path) if project_path else ""
    pattern = r'File "([^"]+)", line (\d+), in'
    matches = re.findall(pattern, error_message)
    if not matches:
        return None, None
    for file_path, line_str in reversed(matches):
        abs_path = os.path.abspath(file_path)
        rel_path = None
        if project_abs and os.path.exists(project_abs):
            try:
                rel_candidate = os.path.relpath(abs_path, project_abs)
                if not rel_candidate.startswith(".."):
                    rel_path = rel_candidate.replace("\\", "/")
            except ValueError:
                rel_path = None
        if not rel_path:
            rel_path = os.path.basename(abs_path)
        matched_index = None
        if isinstance(task_queue, list):
            for idx, task in enumerate(task_queue):
                file_name = task.get("file_name") if isinstance(task, dict) else None
                if file_name and file_name in rel_path:
                    matched_index = idx
                    rel_path = file_name
                    break
        description = f"Fix runtime error at line {line_str} in {rel_path}"
        fix_task = {
            "file_name": rel_path,
            "description": description,
            "runtime_fix": True,
            "runtime_fix_noqueue": matched_index is None,
        }
        return fix_task, matched_index
    return None, None


def run_code_forward(input: dict, attributes: dict) -> dict:
    """
    Execute the generated code locally, collect runtime errors, and persist the
    updated codebase. Execution happens via the local Python interpreter rather
    than an LLM.
    """
    import tempfile
    import subprocess
    import sys
    import os
    

    current_task = attributes.get("current_task", {})
    codebase = attributes.get("codebase", {})
    code = input.get("code", "")
    file_name = input.get("file_name", "")
    project_path = attributes.get("project_path", "./projects/default")
    project_root = Path(project_path).resolve()
    project_root.mkdir(parents=True, exist_ok=True)
    

    if project_path:

        project_path = os.path.normpath(project_path)

        if not os.path.isabs(project_path) and not project_path.startswith('./'):
            project_path = os.path.join('.', project_path)
    

    if code and file_name:
        logger.debug(f"  → Received code for {file_name} ({len(code)} chars)")
    elif not code:
        logger.warning(f"  ⚠️  No code received for task: {current_task}")
    elif not file_name:
        logger.warning(f"  ⚠️  No file_name received, code length: {len(code)}")
    

    if file_name and code:
        codebase[file_name] = code
        attributes["codebase"] = codebase
        logger.debug(f"  ✓ Added {file_name} to codebase (total: {len(codebase)} files)")
        logger.debug(f"✓ Code generated for {file_name} ({len(code)} characters)")
    
    run_status = "success"
    runtime_log = ""
    error_message = ""
    stdout = ""
    stderr = ""
    

    logger.debug(f"  → RunCode: code={bool(code)}, file_name={file_name}")
    
    if code and file_name:
        def _sync_codebase_to_disk():
            if not isinstance(codebase, dict):
                return
            for fname, content in codebase.items():
                if not fname:
                    continue
                file_path = project_root / fname
                file_path.parent.mkdir(parents=True, exist_ok=True)
                try:
                    file_path.write_text(str(content), encoding="utf-8")
                except Exception as err:
                    logger.warning(f"  ⚠️  Warning: Failed to write {file_path}: {err}")
        
        _sync_codebase_to_disk()
        exec_file_path = project_root / file_name
        exec_file_path.parent.mkdir(parents=True, exist_ok=True)
        if not exec_file_path.exists():
            try:
                exec_file_path.write_text(str(code), encoding="utf-8")
            except Exception as err:
                logger.warning(f"  ⚠️  Warning: Failed to write {exec_file_path}: {err}")
        exec_rel_path = os.path.relpath(exec_file_path, project_root)
        is_test_file = (
            file_name.startswith("tests/")
            or "/tests/" in file_name
            or file_name.startswith("test_")
            or file_name.endswith("_test.py")
        )
        
        if is_test_file:
            env = os.environ.copy()
            env["PYTHONPATH"] = f"{project_root}{os.pathsep}{env.get('PYTHONPATH', '')}".rstrip(os.pathsep)
            try:
                process = subprocess.run(
                    [sys.executable, "-m", "pytest", exec_rel_path],
                    cwd=project_root,
                    capture_output=True,
                    text=True,
                    timeout=30,
                    env=env,
                )
                stdout = process.stdout
                stderr = process.stderr
                if process.returncode == 0:
                    run_status = "success"
                    runtime_log = f"Pytest passed for {file_name}\nSTDOUT:\n{stdout}"
                    if stderr:
                        runtime_log += f"\nSTDERR:\n{stderr}"
                else:
                    run_status = "error"
                    error_message = stderr or f"pytest exited with code {process.returncode}"
                    runtime_log = f"Pytest failed for {file_name}\nSTDERR:\n{stderr}\nSTDOUT:\n{stdout}"
            except subprocess.TimeoutExpired:
                run_status = "error"
                error_message = f"pytest timeout for {file_name}"
                runtime_log = f"pytest timeout for {file_name}"
            except Exception as err:
                run_status = "error"
                error_message = str(err)
                runtime_log = f"pytest execution error for {file_name}: {error_message}"
        else:
            try:
                if file_name.endswith(".py"):
                    compile(code, file_name, "exec")
                
                is_executable = (
                    'if __name__ == "__main__"' in code or
                    '__main__' in code or
                    any(keyword in code for keyword in ['print(', 'main()', 'app.run(', 'if __name__'])
                )
                
                if file_name.endswith(".py") and is_executable:
                    try:
                        process = subprocess.run(
                            [sys.executable, exec_rel_path],
                            capture_output=True,
                            text=True,
                            timeout=10,
                            stdin=subprocess.DEVNULL,
                            cwd=project_root,
                        )
                        
                        stdout = process.stdout
                        stderr = process.stderr
                        
                        if process.returncode == 0:
                            run_status = "success"
                            runtime_log = f"Code executed successfully for {file_name}\nSTDOUT:\n{stdout}"
                            if stderr:
                                runtime_log += f"\nSTDERR:\n{stderr}"
                        else:
                            has_input = 'input(' in code or 'raw_input(' in code
                            is_eof_error = 'EOFError' in stderr or 'EOF when reading a line' in stderr
                            
                            if has_input and is_eof_error:
                                run_status = "skipped_cli"
                                error_message = "Code requires user input, execution skipped"
                                runtime_log = f"Execution skipped for {file_name}: CLI application requires user input\nSTDERR:\n{stderr}"
                                logger.warning(f"  ⚠️  Skipping execution for CLI code ({file_name}): EOFError indicates user input required")
                            else:
                                run_status = "error"
                                error_message = stderr or f"Process exited with code {process.returncode}"
                                runtime_log = f"Execution error in {file_name}:\nSTDERR:\n{stderr}\nSTDOUT:\n{stdout}"
                    except subprocess.TimeoutExpired:
                        has_input = 'input(' in code or 'raw_input(' in code
                        is_gui_loop = 'tkinter' in code or 'mainloop()' in code
                        if has_input:
                            run_status = "skipped_cli"
                            error_message = "Code requires user input, execution skipped"
                            runtime_log = f"Execution skipped for {file_name}: CLI application requires user input"
                            logger.warning(f"  ⚠️  Skipping execution for CLI code ({file_name}): requires user input")
                        elif is_gui_loop:
                            run_status = "skipped_gui"
                            error_message = ""
                            runtime_log = f"Execution skipped for {file_name}: detected GUI main loop (likely running correctly)"
                            logger.warning(f"  ⚠️  Skipping execution for GUI code ({file_name}): mainloop detected, treating timeout as success")
                        else:
                            run_status = "error"
                            error_message = "Execution timeout (10s)"
                            runtime_log = f"Execution timeout for {file_name}"
                    except KeyboardInterrupt:
                        run_status = "error"
                        error_message = "Execution interrupted by user"
                        runtime_log = f"Execution interrupted for {file_name}"
                        logger.warning(f"  ⚠️  Warning: Code execution was interrupted")
                    except Exception as e:
                        run_status = "error"
                        error_message = str(e)
                        runtime_log = f"Execution error in {file_name}: {error_message}"
                else:
                    runtime_log = f"Syntax check passed for {file_name} (non-executable file)"
            except SyntaxError as e:
                run_status = "error"
                error_message = str(e)
                runtime_log = f"Syntax error in {file_name}: {error_message}"
            except Exception as e:
                run_status = "error"
                error_message = str(e)
                runtime_log = f"Error in {file_name}: {error_message}"
    
    if run_status == "error" and error_message:
        task_queue = attributes.get("task_queue", [])
        fix_task, fix_index = _extract_runtime_fix_task(error_message, project_path, task_queue)
        if fix_task:
            attributes["runtime_fix_task"] = fix_task
            attributes["runtime_fix_task_index"] = fix_index
            logger.debug(f"  → Queued runtime fix task for {fix_task['file_name']}")
    
    return {
        "current_task": current_task,
        "codebase": codebase,
        "run_status": run_status,
        "runtime_log": runtime_log,
        "error_message": error_message,
        "stdout": stdout,
        "stderr": stderr,
        "current_task_retry_count": input.get("current_task_retry_count", attributes.get("current_task_retry_count", 0)),
    }


def _write_codebase_to_disk(codebase: dict, project_path: str) -> list[str]:
    """
    Helper to persist the current codebase to disk.
    Returns the list of files that were successfully written.
    """
    if not codebase:
        return []
    if not project_path:
        project_path = "./projects/default"

    normalized_path = os.path.normpath(project_path)
    base_path = Path(normalized_path)
    if not base_path.is_absolute():
        base_path = (Path.cwd() / base_path).resolve()

    files_written: list[str] = []
    for file_name, code_content in codebase.items():
        if not file_name:
            continue
        target_path = base_path / file_name
        target_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            target_path.write_text(str(code_content) if code_content is not None else "", encoding="utf-8")
            files_written.append(file_name)
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"  ⚠️  Warning: Failed to write file {target_path}: {exc}")
    return files_written


def update_task_state_forward(input: dict, attributes: dict) -> dict:
    """
    Update the workflow state once a task completes, persist emitted files, and
    advance the task pointer.
    """
    codebase = input.get("codebase", {})
    current_task = input.get("current_task", {})

    project_path = input.get("project_path") or attributes.get("project_path", "./projects/default")
    runtime_fix_noqueue = attributes.pop("runtime_fix_current_noqueue", False)
    

    if project_path:
        project_path = os.path.normpath(project_path)
        if not os.path.isabs(project_path) and not project_path.startswith('./'):
            project_path = os.path.join('.', project_path)
    

    logger.debug(f"\n{'='*60}")
    logger.debug(f"[UpdateTaskState] CALLED!")
    logger.debug(f"  → codebase has {len(codebase)} files")
    logger.debug(f"  → project_path = {project_path}")
    logger.debug(f"  → current_task = {current_task}")
    logger.debug(f"{'='*60}\n")
    

    if codebase:
        attributes["codebase"] = codebase
        files_written = _write_codebase_to_disk(codebase, project_path)
        if files_written:
            logger.debug(f"  ✓ Written {len(files_written)} files to {project_path}: {', '.join(files_written)}")
        else:
            logger.warning(f"  ⚠️  No files written: codebase has {len(codebase)} entries but none were written")
    else:
        logger.warning(f"  ⚠️  UpdateTaskState: codebase is empty!")
    

    idx = attributes.get("current_task_index", 0)
    new_idx = idx if runtime_fix_noqueue else idx + 1
    attributes["current_task_index"] = new_idx
    

    logger.debug(f"  → Updated current_task_index: {idx} -> {new_idx}")
    
    return {
        "current_task_index": new_idx,
        "codebase": codebase,
        "current_task_retry_count": input.get("current_task_retry_count", attributes.get("current_task_retry_count", 0)),
    }


def test_executor_forward(input: dict, attributes: dict) -> dict:
    """
    Execute generated test code locally, capture pass/fail statistics, and return
    a structured report for downstream consumption.
    """
    test_code = input.get("test_code", "")
    test_file_name = input.get("test_file_name", "test_main.py")

    codebase = attributes.get("codebase", {})
    project_path = attributes.get("project_path", "./projects/default")
    
    test_status = "not_run"
    test_output = ""
    test_errors = ""
    passed_tests = 0
    failed_tests = 0
    

    logger.debug(f"\n{'='*60}")
    logger.debug(f"[TestExecutor] Called!")
    logger.debug(f"  → test_code length: {len(test_code) if test_code else 0}")
    logger.debug(f"  → test_file_name: {test_file_name}")
    logger.debug(f"  → codebase files: {list(codebase.keys()) if isinstance(codebase, dict) else 'N/A'}")
    logger.debug(f"{'='*60}\n")
    
    if test_code and test_file_name:
        try:

            with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
                temp_test_file = f.name


                for file_name, code_content in codebase.items():
                    if file_name.endswith(".py") and file_name != test_file_name:

                        f.write(f"# Code from {file_name}\n")
                        f.write(code_content)
                        f.write("\n\n")

                f.write("# Test code\n")
                f.write(test_code)
                f.flush()
            
            try:


                process = subprocess.run(
                    [sys.executable, temp_test_file],
                    capture_output=True,
                    text=True,
                    timeout=30,
                    stdin=subprocess.DEVNULL,
                    cwd=project_path if os.path.exists(project_path) else None,
                )
                
                test_output = process.stdout
                test_errors = process.stderr
                

                logger.debug(f"  → Test process returncode: {process.returncode}")
                if test_output:
                    logger.debug(f"  → Test stdout (first 500 chars): {test_output[:500]}")
                if test_errors:
                    logger.debug(f"  → Test stderr (first 500 chars): {test_errors[:500]}")
                
                if process.returncode == 0:
                    test_status = "passed"

                    passed_tests = test_output.count("ok") + test_output.count("PASSED") + test_output.count("passed")
                    if passed_tests == 0:

                        passed_tests = 1
                        test_output = test_output or "Test execution completed successfully (no explicit test framework output)"
                else:
                    test_status = "failed"

                    failed_tests = test_errors.count("FAILED") + test_errors.count("FAIL") + test_errors.count("Error") + test_errors.count("Traceback")
                    if failed_tests == 0:

                        failed_tests = 1
            except subprocess.TimeoutExpired:
                test_status = "timeout"
                test_errors = "Test execution timeout (60s)"
            except Exception as e:
                test_status = "error"
                test_errors = str(e)
            finally:

                try:
                    os.unlink(temp_test_file)
                except:
                    pass
        except Exception as e:
            test_status = "error"
            test_errors = str(e)
    

    if not test_code:
        test_status = "not_run"
        test_output = "No test code provided by QA Engineer"
        test_errors = ""
        passed_tests = 0
        failed_tests = 0
    

    test_report = {
        "status": test_status,
        "passed_tests": passed_tests,
        "failed_tests": failed_tests,
        "output": test_output,
        "errors": test_errors,
        "summary": f"Tests: {passed_tests} passed, {failed_tests} failed. Status: {test_status}",
    }
    

    logger.debug(f"\n{'='*60}")
    logger.debug(f"[TestExecutor] Test Report:")
    logger.debug(f"  → Status: {test_status}")
    logger.debug(f"  → Passed: {passed_tests}, Failed: {failed_tests}")
    logger.debug(f"  → Summary: {test_report['summary']}")
    logger.debug(f"{'='*60}\n")
    
    return {
        "test_report": test_report,
        "test_status": test_status,
        "codebase": codebase,
    }


def integration_checker_forward(input: dict, attributes: dict) -> dict:
    """
    Integration checker that validates the generated project structure by
    ensuring `main.py` exists, modules are imported, and no placeholder files
    remain. It surfaces actionable issues as part of the build report.
    """
    codebase = input.get("codebase", {})
    project_path = attributes.get("project_path", "./projects/default")
    project_name = attributes.get("project_name") or Path(project_path).name
    is_humaneval_project = "humaneval" in str(project_name).lower()
    
    logger.debug(f"\n{'='*60}")
    logger.debug(f"[IntegrationChecker] Checking code integration...")
    logger.debug(f"  → Codebase files: {list(codebase.keys())}")
    logger.debug(f"{'='*60}\n")
    
    issues = []
    warnings = []
    fixes_needed = []
    
    requires_main_module = not is_humaneval_project


    if requires_main_module:
        has_main = "main.py" in codebase
        if not has_main:
            issues.append("❌ Missing main.py file - no entry point found")
            fixes_needed.append({
                "type": "missing_main",
                "description": "Create main.py that integrates all modules",
                "priority": "high"
            })
        else:
            logger.debug(f"  ✓ Found main.py")
            main_code = codebase.get("main.py", "")
            

            module_files = [f for f in codebase.keys() if f.endswith(".py") and f != "main.py"]
            logger.debug(f"  → Module files (excluding main.py): {module_files}")
            
            if not module_files:
                warnings.append("⚠️  No module files found (only main.py exists)")
            else:

                missing_imports = []
                for module_file in module_files:
                    module_name = module_file.replace(".py", "")
                    import_patterns = [
                        f"from {module_name} import",
                        f"import {module_name}",
                        f"from .{module_name} import",
                        f"from . import {module_name}",
                    ]
                    has_import = any(pattern in main_code for pattern in import_patterns)
                    if not has_import:
                        missing_imports.append(module_file)
                        warnings.append(f"⚠️  main.py does not import {module_file}")
                
                if missing_imports:
                    fixes_needed.append({
                        "type": "missing_imports",
                        "description": f"main.py should import: {', '.join(missing_imports)}",
                        "priority": "high",
                        "missing_modules": missing_imports
                    })
                else:
                    logger.debug(f"  ✓ main.py imports all modules")
                
                if 'if __name__ == "__main__"' not in main_code:
                    warnings.append("⚠️  main.py does not have executable entry point (if __name__ == '__main__')")
                else:
                    logger.debug(f"  ✓ main.py has executable entry point")
                
                placeholder_patterns = ['pass  #', 'pass\n', 'TODO', '# TODO', 'NotImplementedError', 'raise NotImplementedError']
                has_placeholder = any(pattern in main_code for pattern in placeholder_patterns)
                if has_placeholder:
                    issues.append("⚠️  main.py contains placeholder code (pass, TODO, etc.)")
                    fixes_needed.append({
                        "type": "placeholder_code",
                        "description": "Replace placeholder code with actual implementation",
                        "priority": "medium"
                    })
                else:
                    logger.debug(f"  ✓ main.py has no placeholder code")
    else:
        has_main = True  # HumanEval projects do not require main.py
        if "solution.py" not in codebase:
            issues.append("❌ HumanEval project is missing solution.py")
            fixes_needed.append({
                "type": "missing_solution",
                "description": "Ensure solution.py exists for HumanEval tasks",
                "priority": "high"
            })
        else:
            logger.debug("  ✓ Detected solution.py for HumanEval, skipping main.py check")
    

    for module_file, module_code in codebase.items():
        if module_file == "main.py":
            continue
        placeholder_patterns = ['pass  #', 'pass\n', 'TODO', '# TODO', 'NotImplementedError']
        has_placeholder = any(pattern in module_code for pattern in placeholder_patterns)
        if has_placeholder:
            issues.append(f"⚠️  {module_file} contains placeholder code")
            fixes_needed.append({
                "type": "placeholder_code",
                "description": f"Replace placeholder code in {module_file} with actual implementation",
                "priority": "medium",
                "file": module_file
            })
    

    integration_status = "passed" if not issues else "issues_found"
    check_report = {
        "status": integration_status,
        "has_main": has_main,
        "requires_main": requires_main_module,
        "issues": issues,
        "warnings": warnings,
        "fixes_needed": fixes_needed,
        "module_count": len([f for f in codebase.keys() if f.endswith(".py") and f != "main.py"]),
        "summary": f"Integration check: {'✓ All checks passed' if not issues else f'⚠️  Found {len(issues)} issues'}"
    }
    
    logger.debug(f"\n{'='*60}")
    logger.debug(f"[IntegrationChecker] Check Report:")
    logger.debug(f"  → Status: {integration_status}")
    logger.debug(f"  → Has main.py: {has_main}")
    logger.debug(f"  → Module count: {check_report['module_count']}")
    logger.debug(f"  → Issues found: {len(issues)}")
    if issues:
        for issue in issues:
            logger.debug(f"    {issue}")
    if warnings:
        logger.debug(f"  → Warnings: {len(warnings)}")
        for warning in warnings:
            logger.debug(f"    {warning}")
    logger.debug(f"  → Summary: {check_report['summary']}")
    logger.debug(f"{'='*60}\n")
    



    
    return {
        "codebase": codebase,
        "integration_check_report": check_report,
        "integration_status": integration_status,
    }


def result_assembler_forward(input: dict, attributes: dict) -> dict:
    """Assemble the final project report combining PRD, design, code, and tests."""
    codebase = input.get("codebase", {})
    test_report = input.get("test_report", {})
    project_path = attributes.get("project_path", "./projects/default")

    prd = input.get("prd") or attributes.get("prd", {})
    system_design = input.get("system_design") or attributes.get("system_design", {})
    


    if isinstance(prd, dict):

        prd_text = prd.get('introduction', '') or prd.get('summary', '') or prd.get('content', '')
        if not prd_text:

            import json
            prd_text = json.dumps(prd, indent=2, ensure_ascii=False)
        prd_summary = prd_text if prd_text else str(prd)
    else:
        prd_summary = str(prd)
    

    if isinstance(system_design, dict):

        design_text = system_design.get('introduction', '') or system_design.get('summary', '') or system_design.get('content', '')
        if not design_text:

            import json
            design_text = json.dumps(system_design, indent=2, ensure_ascii=False)
        design_summary = design_text if design_text else str(system_design)
    else:
        design_summary = str(system_design)
    

    test_summary = test_report.get('summary', str(test_report)) if isinstance(test_report, dict) else str(test_report)
    
    final_answer = f"""
# Project Overview
{prd_summary}

# System Design
{design_summary}

# Generated Files ({len(codebase)})
{chr(10).join(f"- {name}" for name in codebase.keys())}

# Test Report
{test_summary}

Project files saved to: {project_path}

Please inspect the generated sources for full implementation details.
"""
    
    attachments = {
        "codebase": codebase,
        "prd": prd,
        "system_design": system_design,
        "test_report": test_report,
        "project_path": project_path,
    }
    
    return {
        "final_answer": final_answer,
        "attachments": attachments,
    }
