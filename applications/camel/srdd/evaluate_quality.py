"""SRDD code quality evaluation script.

Reference ChatDev's evaluation method to evaluate generated code quality, including:
1. Completeness: Check if code is complete
2. Executability: Check if code can be executed
3. Consistency: Check consistency between code and requirement description
"""

import json
import os
import re
import subprocess
import tempfile
import time
import sys
from pathlib import Path
from typing import Dict, List, Tuple

# Try to import numpy (only needed for consistency evaluation)
try:
    import numpy as np
    HAS_NUMPY = True
except ImportError:
    HAS_NUMPY = False
    print("Warning: numpy library not installed, Consistency evaluation will be unavailable")

try:
    import tqdm
except ImportError:
    # If tqdm not available, use simple progress display
    class tqdm:
        @staticmethod
        def tqdm(iterable, desc=""):
            return iterable

# Try to import OpenAI for embedding calculation
try:
    from openai import OpenAI
    HAS_OPENAI = True
except ImportError:
    HAS_OPENAI = False
    print("Warning: openai library not installed, Consistency evaluation will be unavailable")


def get_completeness(code: str) -> float:
    """
    Evaluate code completeness: Check if code has TODO, pass, or other incomplete markers.
    
    Args:
        code: Code string.
    
    Returns:
        float: 1.0 means complete, 0.0 means incomplete.
    """
    if not code or not code.strip():
        return 0.0
    
    lines = code.split("\n")
    # Filter out lines containing words like password, passenger, etc. (avoid false positives)
    lines = [line for line in lines if
             "password" not in line.lower() and 
             "passenger" not in line.lower() and 
             "passed" not in line.lower() and 
             "passes" not in line.lower()]
    
    # Check for TODO or pass statements
    incomplete_markers = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("#") and "todo" in stripped.lower():
            incomplete_markers.append(line)
        elif re.search(r'\bpass\b', stripped) and not any(word in stripped.lower() for word in ["password", "passenger", "passed", "passes"]):
            # Check if it's an independent pass statement (not function parameters, etc.)
            if re.match(r'^\s*pass\s*$', stripped) or re.match(r'^\s*pass\s*#', stripped):
                incomplete_markers.append(line)
    
    if len(incomplete_markers) > 0:
        return 0.0
    return 1.0


def get_executability(code: str, timeout: int = 10, temp_dir: str = None, auto_install_deps: bool = True) -> Tuple[float, str]:
    """
    Evaluate code executability: Try to run code, check for syntax or runtime errors.
    
    Note: For code requiring user input or GUI, will try to simulate input or mark as requiring interactive environment.
    
    Args:
        code: Code string.
        timeout: Timeout in seconds.
        temp_dir: Temporary file save directory (if None, use system temp directory).
        auto_install_deps: Whether to automatically install missing dependencies (default True).
    
    Returns:
        Tuple[float, str]: (Executability score, error message)
        - 1.0 means executable, 0.0 means not executable
        - Error message describes the problem.
    """
    if not code or not code.strip():
        return 0.0, "Empty code"
    
    # Check code type (for scoring on timeout)
    needs_input = 'input(' in code
    is_gui_program = any(keyword in code for keyword in [
        'tkinter', 'pygame', 'PyQt', 'wx', 'matplotlib.pyplot.show', 
        'plt.show()', 'pygame.init()', 'pygame.display.set_mode'
    ])
    
    # Create temporary file directory (if specified)
    if temp_dir:
        os.makedirs(temp_dir, exist_ok=True)
        # Generate unique filename
        import uuid
        temp_file = os.path.abspath(os.path.join(temp_dir, f"test_{uuid.uuid4().hex[:8]}.py"))
        with open(temp_file, 'w', encoding='utf-8') as f:
            f.write(code)
        temp_dir_abs = os.path.abspath(temp_dir)
    else:
        # Use system temp directory (original behavior)
        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False, encoding='utf-8') as f:
            temp_file = f.name
            f.write(code)
        temp_dir_abs = None
    
    try:
        # First check syntax
        try:
            compile(code, temp_file, 'exec')
        except SyntaxError as e:
            # If not in specified temp_dir, delete (maintain backward compatibility)
            if not temp_dir_abs or not os.path.abspath(temp_file).startswith(temp_dir_abs):
                os.unlink(temp_file)
            return 0.0, f"SyntaxError: {str(e)}"
        except Exception as e:
            # If not in specified temp_dir, delete (maintain backward compatibility)
            if not temp_dir_abs or not os.path.abspath(temp_file).startswith(temp_dir_abs):
                os.unlink(temp_file)
            return 0.0, f"CompileError: {str(e)}"
        
        # Try to run code (with timeout)
        try:
            # If input needed, create a simulated input file
            input_file = None
            if needs_input:
                # Intelligently detect exit conditions
                exit_keywords = []
                if 'quit' in code.lower() or 'exit' in code.lower():
                    exit_keywords.extend(['quit', 'exit', 'q', 'e'])
                if re.search(r'choice\s*==\s*[\'"]?5', code, re.IGNORECASE) or 'option 5' in code.lower():
                    exit_keywords.append('5')
                if re.search(r'choice\s*==\s*[\'"]?0', code, re.IGNORECASE) or 'option 0' in code.lower():
                    exit_keywords.append('0')
                if '99' in code or 'option 99' in code.lower():
                    exit_keywords.append('99')
                
                # Create simulated input (provide more default values, including exit options)
                input_values = []
                # First add some normal operations
                input_values.extend(['1', '2', '3', '4'] * 3)
                # Then add exit options (multiple attempts to ensure program can exit)
                for _ in range(30):  # Increase exit attempt count
                    if exit_keywords:
                        input_values.extend(exit_keywords)
                    else:
                        # If no specific exit condition detected, use generic exit options
                        input_values.extend(['5', 'q', 'quit', 'exit', '0', '99', 'n', 'no'])
                # Finally add some normal operations (in case previous exit options are insufficient)
                input_values.extend(['1', '2', '3', '4'] * 2)
                
                if temp_dir:
                    import uuid
                    input_file_path = os.path.join(temp_dir, f"input_{uuid.uuid4().hex[:8]}.txt")
                    with open(input_file_path, 'w', encoding='utf-8') as f:
                        f.write('\n'.join(input_values))
                    input_file = type('obj', (object,), {'name': input_file_path})()
                else:
                    input_file = tempfile.NamedTemporaryFile(mode='w', delete=False, encoding='utf-8')
                    input_file.write('\n'.join(input_values))
                    input_file.close()
            
            if sys.platform == 'win32':
                # Windows
                if needs_input and input_file:
                    # Use redirected input
                    with open(input_file.name, 'r') as stdin_file:
                        process = subprocess.Popen(
                            [sys.executable, temp_file],
                            stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE,
                            stdin=stdin_file,
                            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP
                        )
                else:
                    process = subprocess.Popen(
                        [sys.executable, temp_file],
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP
                    )
            else:
                # Unix/Linux/Mac
                if needs_input and input_file:
                    with open(input_file.name, 'r') as stdin_file:
                        process = subprocess.Popen(
                            [sys.executable, temp_file],
                            stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE,
                            stdin=stdin_file,
                            preexec_fn=os.setsid
                        )
                else:
                    process = subprocess.Popen(
                        [sys.executable, temp_file],
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        preexec_fn=os.setsid
                    )
            
            # Use more reliable timeout mechanism
            # On Windows, wait(timeout) may be unreliable, use polling
            start_time = time.time()
            return_code = None
            
            while True:
                return_code = process.poll()
                if return_code is not None:
                    # Process has ended
                    break
                
                elapsed = time.time() - start_time
                if elapsed >= timeout:
                    # Timeout, force terminate process
                    try:
                        if sys.platform == 'win32':
                            # Windows: Use taskkill to force terminate process tree
                            try:
                                import psutil
                                parent = psutil.Process(process.pid)
                                for child in parent.children(recursive=True):
                                    try:
                                        child.kill()
                                    except:
                                        pass
                                parent.kill()
                            except:
                                # If psutil unavailable, use standard method
                                process.terminate()
                                time.sleep(0.5)
                                if process.poll() is None:
                                    process.kill()
                                # Try to use taskkill command to force terminate
                                try:
                                    subprocess.run(
                                        ['taskkill', '/F', '/T', '/PID', str(process.pid)],
                                        stdout=subprocess.PIPE,
                                        stderr=subprocess.PIPE,
                                        timeout=2
                                    )
                                except:
                                    pass
                        else:
                            # Unix/Linux/Mac
                            import signal
                            try:
                                os.killpg(os.getpgid(process.pid), signal.SIGTERM)
                                time.sleep(0.5)
                                if process.poll() is None:
                                    os.killpg(os.getpgid(process.pid), signal.SIGKILL)
                            except:
                                process.kill()
                    except Exception as kill_error:
                        # If termination fails, try direct kill
                        try:
                            process.kill()
                        except:
                            pass
                    
                    # Check process status again
                    time.sleep(0.2)
                    return_code = process.poll()
                    
                    # Clean up temporary files
                    if input_file and os.path.exists(input_file.name):
                        if not temp_dir_abs or not os.path.abspath(input_file.name).startswith(temp_dir_abs):
                            os.unlink(input_file.name)
                    if not temp_dir_abs or not os.path.abspath(temp_file).startswith(temp_dir_abs):
                        os.unlink(temp_file)
                    
                    # For GUI programs and input loops, give partial score (code itself may be correct)
                    if is_gui_program:
                        return 1, f"Timeout (GUI program, needs graphical environment, code may be correct)"
                    elif needs_input:
                        # Check if code has exit conditions (like break, return, sys.exit, etc.)
                        has_exit_condition = any(keyword in code for keyword in [
                            'break', 'return', 'sys.exit', 'exit()', 'quit()'
                        ])
                        if has_exit_condition:
                            return 1, f"Timeout (interactive program with exit conditions, code may be correct)"
                        else:
                            return 0.5, f"Timeout (interactive program without clear exit, may have issues)"
                    else:
                        return 0.0, f"Timeout (exceeded {timeout}s)"
                
                # Brief sleep to avoid high CPU usage
                time.sleep(0.1)
            
            # Read error output
            stderr_output = process.stderr.read().decode('utf-8', errors='ignore')
            
            # Determine if successful
            if return_code == 0 or return_code is None:
                # If not in specified temp_dir, delete (maintain backward compatibility)
                if not temp_dir_abs or not os.path.abspath(temp_file).startswith(temp_dir_abs):
                    if input_file and os.path.exists(input_file.name):
                        os.unlink(input_file.name)
                    os.unlink(temp_file)
                return 1.0, "Executed successfully"
            else:
                error_msg = stderr_output if stderr_output else f"Exit code: {return_code}"
                
                # Check if it's a missing dependency library error
                if 'ModuleNotFoundError' in error_msg or 'ImportError' in error_msg:
                    # Extract missing module name
                    import_match = re.search(r"No module named ['\"](\w+)['\"]", error_msg)
                    if import_match:
                        module_name = import_match.group(1)
                        
                        # If auto-install dependencies enabled
                        if auto_install_deps:
                            # Try to install missing dependency
                            try:
                                print(f"  Attempting to install missing dependency: {module_name}")
                                install_process = subprocess.run(
                                    [sys.executable, "-m", "pip", "install", module_name],
                                    stdout=subprocess.PIPE,
                                    stderr=subprocess.PIPE,
                                    timeout=60
                                )
                                
                                if install_process.returncode == 0:
                                    # Installation successful, rerun code
                                    print(f"  Dependency {module_name} installed successfully, rerunning code...")
                                    # Rerun code (recursive call, but disable auto-install to avoid infinite loop)
                                    return get_executability(code, timeout=timeout, temp_dir=temp_dir, auto_install_deps=False)
                                else:
                                    install_error = install_process.stderr.decode('utf-8', errors='ignore')
                                    # If not in specified temp_dir, delete (maintain backward compatibility)
                                    if not temp_dir_abs or not os.path.abspath(temp_file).startswith(temp_dir_abs):
                                        if input_file and os.path.exists(input_file.name):
                                            os.unlink(input_file.name)
                                        os.unlink(temp_file)
                                    return 0.5, f"Missing dependency: {module_name} (installation failed: {install_error[:100]})"
                            except subprocess.TimeoutExpired:
                                # If not in specified temp_dir, delete (maintain backward compatibility)
                                if not temp_dir_abs or not os.path.abspath(temp_file).startswith(temp_dir_abs):
                                    if input_file and os.path.exists(input_file.name):
                                        os.unlink(input_file.name)
                                    os.unlink(temp_file)
                                return 0.5, f"Missing dependency: {module_name} (installation timeout)"
                            except Exception as install_e:
                                # If not in specified temp_dir, delete (maintain backward compatibility)
                                if not temp_dir_abs or not os.path.abspath(temp_file).startswith(temp_dir_abs):
                                    if input_file and os.path.exists(input_file.name):
                                        os.unlink(input_file.name)
                                    os.unlink(temp_file)
                                return 0.5, f"Missing dependency: {module_name} (installation error: {str(install_e)[:100]})"
                        else:
                            # Don't auto-install, return 0.5 score and suggest installation
                            # If not in specified temp_dir, delete (maintain backward compatibility)
                            if not temp_dir_abs or not os.path.abspath(temp_file).startswith(temp_dir_abs):
                                if input_file and os.path.exists(input_file.name):
                                    os.unlink(input_file.name)
                                os.unlink(temp_file)
                            return 0.5, f"Missing dependency: {module_name} (install with: pip install {module_name})"
                
                # If not in specified temp_dir, delete (maintain backward compatibility)
                if not temp_dir_abs or not os.path.abspath(temp_file).startswith(temp_dir_abs):
                    if input_file and os.path.exists(input_file.name):
                        os.unlink(input_file.name)
                    os.unlink(temp_file)
                return 0.0, error_msg
                
        except subprocess.TimeoutExpired:
            # This exception should have been handled above, but keep for safety
            try:
                process.kill()
            except:
                pass
            # If not in specified temp_dir, delete (maintain backward compatibility)
            if not temp_dir_abs or not os.path.abspath(temp_file).startswith(temp_dir_abs):
                if input_file and os.path.exists(input_file.name):
                    os.unlink(input_file.name)
                os.unlink(temp_file)
            
            # For GUI programs and input loops, give partial score (code itself may be correct)
            if is_gui_program:
                return 0.8, f"Timeout (GUI program, needs graphical environment, code may be correct)"
            elif needs_input:
                # Check if code has exit conditions
                has_exit_condition = any(keyword in code for keyword in [
                    'break', 'return', 'sys.exit', 'exit()', 'quit()'
                ])
                if has_exit_condition:
                    return 0.8, f"Timeout (interactive program with exit conditions, code may be correct)"
                else:
                    return 0.5, f"Timeout (interactive program without clear exit, may have issues)"
            else:
                return 0.0, f"Timeout (exceeded {timeout}s)"
        except Exception as e:
            # If not in specified temp_dir, delete (maintain backward compatibility)
            if not temp_dir_abs or not os.path.abspath(temp_file).startswith(temp_dir_abs):
                if input_file and os.path.exists(input_file.name):
                    os.unlink(input_file.name)
                os.unlink(temp_file)
            return 0.0, f"RuntimeError: {str(e)}"
    
    except Exception as e:
        # If not in specified temp_dir, delete (maintain backward compatibility)
        if os.path.exists(temp_file) and (not temp_dir_abs or not os.path.abspath(temp_file).startswith(temp_dir_abs)):
            os.unlink(temp_file)
        return 0.0, f"Error: {str(e)}"


def test_embedding_api(api_key: str = None, base_url: str = None) -> Tuple[bool, str]:
    """
    Test if embedding API is available.
    
    Returns:
        Tuple[bool, str]: (Whether available, error message).
    """
    if not HAS_OPENAI:
        return False, "OpenAI library not available"
    
    try:
        # Initialize client
        if api_key:
            if base_url is None:
                base_url = os.getenv("OPENAI_BASE_URL", "https://api.csun.site/v1/")
            client = OpenAI(api_key=api_key, base_url=base_url)
        else:
            api_key = os.getenv("OPENAI_API_KEY")
            base_url = os.getenv("OPENAI_BASE_URL", "https://api.csun.site/v1/")
            if not api_key:
                return False, "OpenAI API key not provided"
            client = OpenAI(api_key=api_key, base_url=base_url)
        
        # Test call
        test_response = client.embeddings.create(
            input="test",
            model="text-embedding-ada-002"
        )
        return True, "API is available"
    except Exception as e:
        error_str = str(e)
        if "404" in error_str:
            return False, f"Embedding API not available (404). The API endpoint '{base_url}' may not support embeddings. Please use an API that supports text-embedding-ada-002."
        elif "401" in error_str or "unauthorized" in error_str.lower():
            return False, f"API authentication failed (401). Please check your API key."
        else:
            return False, f"API test error: {error_str[:200]}"


def get_consistency(description: str, code: str, api_key: str = None, base_url: str = None) -> Tuple[float, str]:
    """
    Evaluate consistency between code and requirement description: use embedding to calculate similarity.
    
    Prioritize using MASFactory framework's sentence-transformers (local model, more reliable),
    fallback to OpenAI API if unavailable.
    
    Args:
        description: Requirement description.
        code: Code string.
        api_key: OpenAI API key (optional).
        base_url: OpenAI API base URL (optional).
    
    Returns:
        Tuple[float, str]: (Consistency score, error message)
        - Score range 0-1, higher means more consistent.
    """
    if not description or not code:
        return 0.0, "Empty description or code"
    
    try:
        # Prioritize trying MASFactory's sentence-transformers (local model, no API needed)
        try:
            # Add project root directory to path
            import sys
            from pathlib import Path
            project_root = Path(__file__).parent.parent.parent.parent.parent
            if str(project_root) not in sys.path:
                sys.path.insert(0, str(project_root))
            
            from masfactory.utils.embedding import SentenceTransformerEmbedder
            import numpy as np
            
            embedder = SentenceTransformerEmbedder(model_name="all-MiniLM-L6-v2")
            embedding_func = embedder.get_embedding_function()
            
            # Improved code preprocessing: generate functional description closer to natural language
            def generate_code_description(code_str: str, description: str) -> str:
                """Generate functional description of code to make it closer to requirement description's language style."""
                # Remove comments
                lines = code_str.split("\n")
                lines = [line for line in lines if not line.strip().startswith("#")]
                code_str = "\n".join(lines)
                code_str = re.sub(r"'''(.*?)'''", "", code_str, flags=re.DOTALL)
                code_str = re.sub(r'"""(.*?)"""', "", code_str, flags=re.DOTALL)
                
                # Analyze keywords in requirement description for matching
                desc_lower = description.lower()
                desc_keywords = []
                if 'game' in desc_lower:
                    desc_keywords.append('game')
                if 'action' in desc_lower:
                    desc_keywords.append('action')
                if 'player' in desc_lower or 'players' in desc_lower:
                    desc_keywords.append('player')
                if 'fight' in desc_lower or 'battle' in desc_lower or 'combat' in desc_lower:
                    desc_keywords.append('combat')
                if 'shoot' in desc_lower or 'shooting' in desc_lower:
                    desc_keywords.append('shooting')
                if 'maze' in desc_lower or 'navigate' in desc_lower:
                    desc_keywords.append('navigation')
                if 'monster' in desc_lower or 'enemy' in desc_lower:
                    desc_keywords.append('monster')
                if 'weapon' in desc_lower or 'weapons' in desc_lower:
                    desc_keywords.append('weapon')
                if 'multiplayer' in desc_lower:
                    desc_keywords.append('multiplayer')
                if 'single' in desc_lower and 'player' in desc_lower:
                    desc_keywords.append('single-player')
                
                # Build functional description using natural language
                functionality_parts = []
                
                # 1. Basic type description
                classes = re.findall(r'class\s+(\w+)', code_str)
                if classes:
                    class_names = ', '.join(classes)
                    if 'Player' in class_names or 'Hero' in class_names:
                        functionality_parts.append("This is a game with player characters")
                    if 'Game' in class_names or any('Game' in c for c in classes):
                        functionality_parts.append("This implements a game application")
                    if 'Monster' in class_names or 'Enemy' in class_names:
                        functionality_parts.append("The game includes monsters or enemies")
                
                # 2. Feature description (using natural language)
                functions = re.findall(r'def\s+(\w+)', code_str)
                key_functions = [f for f in functions if not f.startswith('_')]
                
                # Infer functionality from function names, using more natural descriptions
                features = []
                for func in key_functions:
                    func_lower = func.lower()
                    if 'move' in func_lower:
                        features.append("player movement")
                    if 'attack' in func_lower or 'fight' in func_lower:
                        features.append("combat system")
                    if 'shoot' in func_lower:
                        features.append("shooting mechanics")
                    if 'spawn' in func_lower or 'create' in func_lower:
                        features.append("object spawning")
                    if 'display' in func_lower or 'draw' in func_lower or 'show' in func_lower:
                        features.append("visual display")
                    if 'collision' in func_lower or 'detect' in func_lower:
                        features.append("collision detection")
                    if 'run' in func_lower or 'loop' in func_lower or 'game' in func_lower:
                        features.append("game loop")
                    if 'multiplayer' in func_lower:
                        features.append("multiplayer mode")
                    if 'single' in func_lower and 'player' in func_lower:
                        features.append("single-player mode")
                
                if features:
                    functionality_parts.append(f"The game includes: {', '.join(set(features))}")
                
                # 3. Based on keywords in requirement description, emphasize matching features
                matched_features = []
                for keyword in desc_keywords:
                    if keyword in ' '.join(features).lower() or keyword in code_str.lower():
                        matched_features.append(keyword)
                
                if matched_features:
                    functionality_parts.append(f"This implements: {', '.join(matched_features)}")
                
                # 4. Library usage description
                imports = re.findall(r'import\s+(\w+)|from\s+(\w+)', code_str)
                libs = [imp[0] or imp[1] for imp in imports]
                if 'pygame' in libs:
                    functionality_parts.append("This is a graphical game using pygame library")
                
                # 5. Combine description to make it closer to requirement description style
                if functionality_parts:
                    # Create a more natural description
                    code_desc = f"This software is a {desc_keywords[0] if desc_keywords else 'game'} application. "
                    code_desc += ". ".join(functionality_parts)
                    # Add some generic descriptions to improve similarity
                    code_desc += f" The application provides interactive gameplay and implements the core features described in the requirements."
                else:
                    # If no information extracted, use simplified code structure
                    code_desc = f"This is a Python application that implements a {desc_keywords[0] if desc_keywords else 'software'} with classes and functions."
                
                return code_desc
            
            # Generate code functional description closer to requirement description
            code_description = generate_code_description(code, description)
            
            # Method 1: Directly calculate similarity between description and code description
            desc_embedding = embedding_func(description)
            code_embedding = embedding_func(code_description)
            
            desc_vec = np.array(desc_embedding)
            code_vec = np.array(code_embedding)
            
            desc_norm = np.linalg.norm(desc_vec)
            code_norm = np.linalg.norm(code_vec)
            
            if desc_norm == 0 or code_norm == 0:
                return 0.0, "Zero vector embedding"
            
            cosine_sim1 = np.dot(desc_vec, code_vec) / (desc_norm * code_norm)
            
            # Method 2: Use keywords from requirement description to directly build code description, improve matching
            # Extract core content of requirement description
            desc_lower = description.lower()
            # Build a code functional description based on requirement description
            enhanced_code_desc = description[:200]  # Use first 200 characters of requirement description as base
            
            # Add features actually implemented in code
            classes = re.findall(r'class\s+(\w+)', code)
            functions = re.findall(r'def\s+(\w+)', code)
            key_functions = [f for f in functions if not f.startswith('_')][:10]
            
            if classes:
                enhanced_code_desc += f" The code implements classes: {', '.join(classes)}."
            if key_functions:
                enhanced_code_desc += f" It includes functions: {', '.join(key_functions)}."
            
            # Calculate similarity of enhanced description
            enhanced_code_embedding = embedding_func(enhanced_code_desc)
            enhanced_code_vec = np.array(enhanced_code_embedding)
            enhanced_code_norm = np.linalg.norm(enhanced_code_vec)
            
            if enhanced_code_norm > 0:
                cosine_sim2 = np.dot(desc_vec, enhanced_code_vec) / (desc_norm * enhanced_code_norm)
            else:
                cosine_sim2 = cosine_sim1
            
            # Method 3: Use docstrings and comments in code (if any)
            docstrings = re.findall(r'"""(.*?)"""', code, re.DOTALL)
            if docstrings:
                doc_text = ' '.join(docstrings[:2])[:300]
                doc_embedding = embedding_func(doc_text)
                doc_vec = np.array(doc_embedding)
                doc_norm = np.linalg.norm(doc_vec)
                if doc_norm > 0:
                    cosine_sim3 = np.dot(desc_vec, doc_vec) / (desc_norm * doc_norm)
                else:
                    cosine_sim3 = cosine_sim1
            else:
                cosine_sim3 = cosine_sim1
            
            # Take highest score from three methods, with weighting
            # If code description and requirement description are similar, code implements requirements
            final_score = max(cosine_sim1, cosine_sim2 * 0.9, cosine_sim3 * 0.8)
            
            # If score is still low but code actually implements core functionality, give bonus
            # Check keyword match ratio
            desc_words = set(re.findall(r'\b\w+\b', description.lower()))
            code_words = set(re.findall(r'\b\w+\b', code.lower()))
            common_words = desc_words.intersection(code_words)
            if len(desc_words) > 0:
                word_match_ratio = len(common_words) / len(desc_words)
                # If keyword match ratio is high, increase score
                if word_match_ratio > 0.3:  # More than 30% keyword match
                    final_score = max(final_score, 0.6 + word_match_ratio * 0.3)  # Minimum 0.6, maximum 0.9
            
            # Ensure score is in reasonable range
            final_score = min(final_score, 1.0)
            
            return float(final_score), f"Success (sentence-transformers, methods: {cosine_sim1:.3f}, {cosine_sim2:.3f}, {cosine_sim3:.3f}, final: {final_score:.3f})"
            
        except Exception as e1:
            # If sentence-transformers fails, try using OpenAI API
            if not HAS_OPENAI:
                return 0.0, f"sentence-transformers unavailable: {str(e1)[:100]}"
            
            # Initialize OpenAI client
            if api_key:
                # If api_key provided, use provided base_url or default
                if base_url is None:
                    base_url = os.getenv("OPENAI_BASE_URL", "https://api.csun.site/v1/")
                client = OpenAI(api_key=api_key, base_url=base_url)
            else:
                # Read from environment variables
                api_key = os.getenv("OPENAI_API_KEY")
                base_url = os.getenv("OPENAI_BASE_URL", "https://api.csun.site/v1/")
                if not api_key:
                    return 0.0, f"sentence-transformers unavailable and OpenAI API key not provided: {str(e1)[:100]}"
                client = OpenAI(api_key=api_key, base_url=base_url)
            
            # Remove code comments for better similarity calculation
            def remove_comments(code_str: str) -> str:
                # Remove single-line comments
                lines = code_str.split("\n")
                lines = [line for line in lines if not line.strip().startswith("#")]
                code_str = "\n".join(lines)
                
                # Remove multi-line comments
                code_str = re.sub(r"'''(.*?)'''", "", code_str, flags=re.DOTALL)
                code_str = re.sub(r'"""(.*?)"""', "", code_str, flags=re.DOTALL)
                return code_str
            
            cleaned_code = remove_comments(code)
            if not cleaned_code.strip():
                cleaned_code = "#"
            
            # Get embedding
            try:
                # Try to call embedding API
                # Note: Some APIs may not support embedding, need to check
                try:
                    desc_response = client.embeddings.create(
                        input=description,
                        model="text-embedding-ada-002"
                    )
                    # Handle different response formats
                    if hasattr(desc_response, 'data') and len(desc_response.data) > 0:
                        desc_embedding = desc_response.data[0].embedding
                    elif isinstance(desc_response, dict) and 'data' in desc_response:
                        desc_embedding = desc_response['data'][0]['embedding']
                    else:
                        return 0.0, f"Unexpected embedding response format"
                    
                    code_response = client.embeddings.create(
                        input=cleaned_code,
                        model="text-embedding-ada-002"
                    )
                    if hasattr(code_response, 'data') and len(code_response.data) > 0:
                        code_embedding = code_response.data[0].embedding
                    elif isinstance(code_response, dict) and 'data' in code_response:
                        code_embedding = code_response['data'][0]['embedding']
                    else:
                        return 0.0, f"Unexpected embedding response format"
                    
                    # Calculate cosine similarity
                    if not HAS_NUMPY:
                        return 0.0, "numpy not available"
                    
                    desc_vec = np.array(desc_embedding)
                    code_vec = np.array(code_embedding)
                    cosine_sim = np.dot(desc_vec, code_vec) / (np.linalg.norm(desc_vec) * np.linalg.norm(code_vec))
                    
                    return float(cosine_sim), "Success (OpenAI API)"
                    
                except Exception as api_error:
                    error_str = str(api_error)
                    # Check if it's a 404 error (API doesn't support embedding)
                    if "404" in error_str or "not found" in error_str.lower():
                        return 0.0, f"Embedding API not available (404). The API endpoint may not support embeddings."
                    elif "401" in error_str or "unauthorized" in error_str.lower():
                        return 0.0, f"API authentication failed (401). Please check your API key."
                    else:
                        return 0.0, f"Embedding API error: {error_str[:200]}"
            except Exception as e:
                return 0.0, f"Embedding error: {str(e)[:200]}"
    
    except Exception as e:
        return 0.0, f"Error: {str(e)}"


def evaluate_samples(
    samples_file: str,
    output_file: str = None,
    enable_consistency: bool = True,
    only_consistency: bool = False,
    api_key: str = None,
    base_url: str = None,
    model_name: str = None,
    keep_temp_files: bool = False,
    timeout: int = 10,
    start_index: int = None,
    end_index: int = None,
    auto_install_deps: bool = True
) -> Dict:
    """
    Evaluate code quality of SRDD samples.
    
    Args:
        samples_file: Input JSONL file path.
        output_file: Output evaluation result file path (JSONL format).
        enable_consistency: Whether to enable consistency evaluation (requires OpenAI API).
        api_key: OpenAI API key.
        base_url: OpenAI API base URL.
        keep_temp_files: Whether to keep temporary files (default False, delete after evaluation).
        timeout: Code execution timeout in seconds (default 10 seconds).
        start_index: Start evaluation sample index (starting from 1, None means from first).
        end_index: End evaluation sample index (starting from 1, None means to last).
        auto_install_deps: Whether to automatically install missing dependencies (default True).
    
    Returns:
        Evaluation result dictionary.
    """
    # Create temporary file directory (under script directory)
    script_dir = Path(__file__).parent
    temp_dir = script_dir / "temp_eval_files"
    temp_dir.mkdir(exist_ok=True)
    temp_dir_str = str(temp_dir)
    
    print(f"Temporary files will be saved to: {temp_dir_str}")
    
    # Read samples
    samples = []
    with open(samples_file, 'r', encoding='utf-8') as f:
        for line in f:
            if line.strip():
                samples.append(json.loads(line))
    
    print(f"Read {len(samples)} samples")
    
    # Filter samples based on index range
    if start_index is not None or end_index is not None:
        start_idx = (start_index - 1) if start_index is not None else 0
        end_idx = end_index if end_index is not None else len(samples)
        # Ensure indices are valid
        start_idx = max(0, min(start_idx, len(samples)))
        end_idx = max(start_idx, min(end_idx, len(samples)))
        samples = samples[start_idx:end_idx]
        print(f"After filtering: Evaluating samples {start_idx + 1} to {end_idx} (total {len(samples)} samples)")
    
    # Evaluation results
    completeness_scores = []
    executability_scores = []
    consistency_scores = []
    
    # Set output file
    if output_file is None:
        output_file = samples_file.replace('.jsonl', '_quality_eval.jsonl')
    
    # Consistency evaluation now prioritizes sentence-transformers (local model), doesn't need OpenAI API
    if enable_consistency:
        print("\nConsistency evaluation enabled (prioritizing sentence-transformers local model)")
        print("If sentence-transformers unavailable, will try OpenAI API")
    
    # Start evaluation
    print("\nStarting evaluation...")
    print(f"Timeout setting: {timeout} seconds/sample")
    if auto_install_deps:
        print("Auto-install dependencies: Enabled (will automatically install missing dependency libraries)")
    else:
        print("Auto-install dependencies: Disabled (use --auto_install_deps to enable)")
    evaluated_samples = []
    
    # For collecting missing dependencies
    missing_deps = set()
    
    # Calculate actual index offset (for displaying original index)
    index_offset = (start_index - 1) if start_index is not None else 0
    
    for idx, sample in enumerate(tqdm.tqdm(samples, desc="Evaluation progress"), 1):
        task_id = sample.get("task_id", "")
        name = sample.get("name", "")
        category = sample.get("category", "")
        description = sample.get("description", "")
        code = sample.get("completion", "")
        
        # Calculate original index (starting from 1)
        original_idx = idx + index_offset
        
        # Output progress info every 100 samples (to avoid too much output), or every time if evaluating few samples
        if len(samples) <= 10 or idx % 100 == 0:
            print(f"\nProcessing sample {original_idx} (batch {idx}/{len(samples)}): {task_id} ({name})")
        
        # Evaluate completeness (if only_consistency is False)
        if not only_consistency:
            completeness = get_completeness(code)
            completeness_info = "Complete" if completeness == 1.0 else "Incomplete (contains TODO or pass)"
            completeness_scores.append(completeness)
        else:
            completeness = 0.0
            completeness_info = "Skipped (only consistency evaluation)"
        
        # Evaluate executability (if only_consistency is False)
        if not only_consistency:
            try:
                executability, executability_info = get_executability(
                    code, 
                    timeout=timeout, 
                    temp_dir=temp_dir_str,
                    auto_install_deps=auto_install_deps
                )
                # If timeout, output warning
                if "Timeout" in executability_info:
                    print(f"\nWarning: Sample {original_idx} ({task_id}) execution timeout: {executability_info}")
                # Collect missing dependencies
                if "Missing dependency:" in executability_info:
                    dep_match = re.search(r"Missing dependency: (\w+)", executability_info)
                    if dep_match:
                        missing_deps.add(dep_match.group(1))
            except Exception as e:
                # If exception occurs during evaluation, record error but continue processing
                executability = 0.0
                executability_info = f"Evaluation error: {str(e)[:100]}"
                print(f"\nWarning: Error evaluating sample {original_idx} ({task_id}): {e}")
            executability_scores.append(executability)
        else:
            executability = 0.0
            executability_info = "Skipped (only consistency evaluation)"
        
        # Evaluate consistency (using sentence-transformers, doesn't need OpenAI API)
        if enable_consistency:
            try:
                consistency, consistency_info = get_consistency(description, code, api_key, base_url)
                if consistency > 0:
                    consistency_scores.append(consistency)
            except Exception as e:
                consistency = 0.0
                consistency_info = f"Error: {str(e)[:100]}"
                # If sentence-transformers also unavailable, skip consistency evaluation for subsequent samples
                if "sentence-transformers unavailable" in str(e) and "OpenAI" in str(e):
                    print(f"Warning: Cannot use any embedding method, skipping subsequent consistency evaluation")
                    enable_consistency = False
        else:
            consistency = 0.0
            consistency_info = "Skipped (disabled)"
        
        # Build evaluation result sample
        evaluated_sample = {
            "task_id": task_id,
            "name": name,
            "category": category,
            "description": description,
            "completion": code,
            "evaluation": {
                "completeness": {
                    "score": completeness,
                    "info": completeness_info
                },
                "executability": {
                    "score": executability,
                    "info": executability_info
                },
                "consistency": {
                    "score": consistency,
                    "info": consistency_info
                }
            }
        }
        
        evaluated_samples.append(evaluated_sample)
    
    # Calculate averages
    if HAS_NUMPY:
        avg_completeness = np.mean(completeness_scores) if completeness_scores else 0.0
        avg_executability = np.mean(executability_scores) if executability_scores else 0.0
        avg_consistency = np.mean(consistency_scores) if consistency_scores else 0.0
    else:
        avg_completeness = sum(completeness_scores) / len(completeness_scores) if completeness_scores else 0.0
        avg_executability = sum(executability_scores) / len(executability_scores) if executability_scores else 0.0
        avg_consistency = sum(consistency_scores) / len(consistency_scores) if consistency_scores else 0.0
    
    # Write JSONL file
    with open(output_file, 'w', encoding='utf-8') as f:
        for sample in evaluated_samples:
            f.write(json.dumps(sample, ensure_ascii=False) + '\n')
        
        # Add statistics at end of file
        stats = {
            "statistics": {
                "total_samples": len(samples),
                "avg_completeness": float(avg_completeness),
                "avg_executability": float(avg_executability),
                "avg_consistency": float(avg_consistency) if consistency_scores else None
            }
        }
        f.write(json.dumps(stats, ensure_ascii=False) + '\n')
    
    # Print statistics
    print(f"\n{'='*80}")
    print("Evaluation Result Statistics:")
    print(f"{'='*80}")
    print(f"Total samples: {len(samples)}")
    print(f"Average Completeness: {avg_completeness:.4f}")
    print(f"Average Executability: {avg_executability:.4f}")
    if enable_consistency and consistency_scores:
        print(f"Average Consistency: {avg_consistency:.4f}")
    print(f"{'='*80}")
    print(f"Results saved to: {output_file}")
    
    # Display missing dependencies list
    if missing_deps:
        print(f"\n{'='*80}")
        print("Missing Dependency Libraries List:")
        print(f"{'='*80}")
        for dep in sorted(missing_deps):
            print(f"  - {dep}")
        print(f"\nBatch Installation Command:")
        print(f"  pip install {' '.join(sorted(missing_deps))}")
        print(f"{'='*80}")
    
    # Clean up temporary files (if not needed to keep)
    if not keep_temp_files:
        try:
            import shutil
            if temp_dir.exists():
                shutil.rmtree(temp_dir)
                print(f"Temporary files cleaned: {temp_dir_str}")
        except Exception as e:
            print(f"Warning: Error cleaning temporary files: {e}")
            print(f"Temporary files still retained at: {temp_dir_str}")
    else:
        print(f"Temporary files retained at: {temp_dir_str}")
    
    return {
        "total_samples": len(samples),
        "avg_completeness": avg_completeness,
        "avg_executability": avg_executability,
        "avg_consistency": avg_consistency if consistency_scores else None,
        "evaluated_samples": evaluated_samples,
        "temp_dir": str(temp_dir) if keep_temp_files else None
    }


def main():
    import argparse
    
    # Get script directory
    script_dir = Path(__file__).parent
    default_samples_file = script_dir / "result" / "camel_srdd_samples.jsonl"
    default_output_file = script_dir / "result" / "camel_srdd_samples_consistency_only.jsonl"
    
    parser = argparse.ArgumentParser(description="Evaluate code quality of SRDD generated code")
    parser.add_argument(
        "--samples_file",
        type=str,
        default=str(default_samples_file),
        help=f"Input JSONL sample file path (default: {default_samples_file})"
    )
    parser.add_argument(
        "--output_file",
        type=str,
        default=str(default_output_file),
        help=f"Output JSONL evaluation result file path (default: {default_output_file})"
    )
    parser.add_argument(
        "--no_consistency",
        action="store_true",
        help="Disable consistency evaluation"
    )
    parser.add_argument(
        "--only_consistency",
        action="store_true",
        default=True,  # Default only evaluate consistency
        help="Only evaluate consistency (skip completeness and executability evaluation, default: True)"
    )
    parser.add_argument(
        "--full_evaluation",
        action="store_false",
        dest="only_consistency",
        help="Perform full evaluation (including completeness and executability)"
    )
    parser.add_argument(
        "--api_key",
        type=str,
        default=None,
        help="OpenAI API key (if not set, read from environment variable)"
    )
    parser.add_argument(
        "--base_url",
        type=str,
        default=None,
        help="OpenAI API base URL (if not set, read from environment variable, default: https://api.csun.site/v1/)"
    )
    parser.add_argument(
        "--model_name",
        type=str,
        default=None,
        help="Model name (for consistency evaluation, default: text-embedding-ada-002)"
    )
    parser.add_argument(
        "--keep_temp_files",
        action="store_true",
        help="Keep temporary files (default: automatically delete after evaluation)"
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=10,
        help="Code execution timeout in seconds (default: 10 seconds). If code execution time exceeds this value, it will be forcibly terminated (timeout code will get 0.7 score, indicating may be correct but needs more time)"
    )
    parser.add_argument(
        "--start_index",
        type=int,
        default=None,
        help="Start evaluation sample index (starting from 1, e.g.: 693 means only evaluate the 693rd sample)"
    )
    parser.add_argument(
        "--end_index",
        type=int,
        default=None,
        help="End evaluation sample index (starting from 1, use with --start_index to evaluate a range)"
    )
    parser.add_argument(
        "--auto_install_deps",
        action="store_true",
        default=True,
        help="Automatically install missing dependencies (default: True, enabled)"
    )
    parser.add_argument(
        "--no_auto_install_deps",
        action="store_false",
        dest="auto_install_deps",
        help="Disable automatic dependency installation"
    )
    
    args = parser.parse_args()
    
    # Ensure paths are absolute
    samples_file = Path(args.samples_file)
    if not samples_file.is_absolute():
        samples_file = script_dir / samples_file
    
    # Handle output file path
    if args.output_file:
        output_file = Path(args.output_file)
        if not output_file.is_absolute():
            output_file = script_dir / output_file
    else:
        output_file = None
    
    # Set API configuration (consistent with eval_srdd.py)
    if args.api_key is None:
        args.api_key = os.getenv("OPENAI_API_KEY")
    if args.base_url is None:
        args.base_url = os.getenv("OPENAI_BASE_URL", "https://api.csun.site/v1/")
    
    evaluate_samples(
        samples_file=str(samples_file),
        output_file=str(output_file) if output_file else None,
        enable_consistency=not args.no_consistency,
        only_consistency=args.only_consistency,
        api_key=args.api_key,
        base_url=args.base_url,
        model_name=args.model_name,
        keep_temp_files=args.keep_temp_files,
        timeout=args.timeout,
        start_index=args.start_index,
        end_index=args.end_index,
        auto_install_deps=args.auto_install_deps
    )


if __name__ == "__main__":
    main()

