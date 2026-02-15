"""Tool functions required for GAIA tasks."""

import os
import json
import csv
from pathlib import Path
from typing import Optional, Dict, Any
import math


def read_file(file_path: str) -> str:
    """
    Read file content.
    
    Args:
        file_path: File path (can be absolute path or relative to data directory).
    
    Returns:
        File content string.
    
    Example:
        >>> content = read_file("data.txt")
        >>> content = read_file("/absolute/path/to/file.csv")
    """
    try:
        # If absolute path, read directly
        if os.path.isabs(file_path):
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                return f.read()
        
        # Otherwise try multiple possible paths
        possible_paths = [
            Path(file_path),
            Path(__file__).parent.parent.parent.parent.parent.parent / "datasets" / "gaia" / file_path,
            Path(__file__).parent.parent.parent.parent.parent.parent / "datasets" / "gaia" / "files" / file_path,
            Path(__file__).parent.parent.parent.parent.parent.parent / "datasets" / "gaia" / "attachments" / file_path,
        ]
        
        for path in possible_paths:
            if path.exists() and path.is_file():
                with open(path, 'r', encoding='utf-8', errors='ignore') as f:
                    return f.read()
        
        return f"Error: File not found: {file_path}"
    except Exception as e:
        return f"Error reading file {file_path}: {str(e)}"


def read_csv(file_path: str, delimiter: str = ",") -> str:
    """
    Read CSV file and return formatted content.
    
    Args:
        file_path: CSV file path.
        delimiter: CSV delimiter, default is comma.
    
    Returns:
        Formatted CSV content string.
    """
    try:
        content = read_file(file_path)
        if content.startswith("Error:"):
            return content
        
        # Try to parse CSV
        lines = content.split('\n')
        if not lines:
            return "Error: Empty CSV file"
        
        # Return formatted CSV content
        return content
    except Exception as e:
        return f"Error reading CSV file {file_path}: {str(e)}"


def read_json(file_path: str) -> str:
    """
    Read JSON file and return formatted content.
    
    Args:
        file_path: JSON file path.
    
    Returns:
        Formatted JSON content string.
    """
    try:
        content = read_file(file_path)
        if content.startswith("Error:"):
            return content
        
        # Try to parse JSON to verify format
        json.loads(content)
        return content
    except json.JSONDecodeError as e:
        return f"Error: Invalid JSON in file {file_path}: {str(e)}"
    except Exception as e:
        return f"Error reading JSON file {file_path}: {str(e)}"


def calculate(expression: str) -> str:
    """
    Safely calculate mathematical expression.
    
    Args:
        expression: Mathematical expression string (e.g., "2 + 3 * 4").
    
    Returns:
        Calculation result string.
    
    Example:
        >>> result = calculate("2 + 3 * 4")
        >>> result = calculate("sqrt(16) + log(10)")
    """
    try:
        # Only allow safe mathematical operations
        allowed_names = {
            k: v for k, v in math.__dict__.items() if not k.startswith("__")
        }
        # Remove unsafe functions
        allowed_names.pop('pow', None)  # Use ** instead
        allowed_names.pop('eval', None)
        allowed_names.pop('exec', None)
        
        # Use eval but limit available functions
        result = eval(expression, {"__builtins__": {}}, allowed_names)
        return str(result)
    except Exception as e:
        return f"Error calculating expression '{expression}': {str(e)}"


def list_files(directory: str = ".") -> str:
    """
    List files in directory.
    
    Args:
        directory: Directory path (default is current directory).
    
    Returns:
        File list string.
    """
    try:
        # If absolute path, use directly
        if os.path.isabs(directory):
            dir_path = Path(directory)
        else:
            # Try multiple possible paths
            possible_paths = [
                Path(directory),
                Path(__file__).parent.parent.parent.parent.parent.parent / "datasets" / "gaia" / directory,
                Path(__file__).parent.parent.parent.parent.parent.parent / "datasets" / "gaia" / "files" / directory,
            ]
            dir_path = None
            for path in possible_paths:
                if path.exists() and path.is_dir():
                    dir_path = path
                    break
            
            if dir_path is None:
                return f"Error: Directory not found: {directory}"
        
        files = []
        for item in dir_path.iterdir():
            if item.is_file():
                files.append(item.name)
        
        return "\n".join(files) if files else f"No files found in {directory}"
    except Exception as e:
        return f"Error listing files in {directory}: {str(e)}"


def search_in_file(file_path: str, search_term: str) -> str:
    """
    Search for lines containing specific keyword in file.
    
    Args:
        file_path: File path.
        search_term: Search keyword.
    
    Returns:
        Lines containing keyword (one per line).
    """
    try:
        content = read_file(file_path)
        if content.startswith("Error:"):
            return content
        
        lines = content.split('\n')
        matching_lines = [line for line in lines if search_term.lower() in line.lower()]
        
        if matching_lines:
            return "\n".join(matching_lines)
        else:
            return f"No lines found containing '{search_term}' in {file_path}"
    except Exception as e:
        return f"Error searching in file {file_path}: {str(e)}"


def get_file_info(file_path: str) -> str:
    """
    Get file information (size, line count, etc.).
    
    Args:
        file_path: File path.
    
    Returns:
        File information string.
    """
    try:
        # Try multiple possible paths
        possible_paths = [
            Path(file_path),
            Path(__file__).parent.parent.parent.parent.parent.parent / "datasets" / "gaia" / file_path,
            Path(__file__).parent.parent.parent.parent.parent.parent / "datasets" / "gaia" / "files" / file_path,
        ]
        
        file_path_obj = None
        for path in possible_paths:
            if path.exists() and path.is_file():
                file_path_obj = path
                break
        
        if file_path_obj is None:
            return f"Error: File not found: {file_path}"
        
        size = file_path_obj.stat().st_size
        with open(file_path_obj, 'r', encoding='utf-8', errors='ignore') as f:
            lines = len(f.readlines())
        
        return f"File: {file_path}\nSize: {size} bytes\nLines: {lines}"
    except Exception as e:
        return f"Error getting file info for {file_path}: {str(e)}"

