"""Extract GAIA answers from CAMEL conversation results."""

import re
import json
from typing import Dict, Any, Optional


def extract_answer_from_text(text: str) -> Optional[str]:
    """
    Extract answer from text.
    
    Args:
        text: Text containing answer.
    
    Returns:
        Extracted answer string, or None if not found.
    """
    if not isinstance(text, str):
        text = str(text)
    
    if not text.strip():
        return None
    
    # First try to extract explicit answer markers (highest priority)
    explicit_answer_patterns = [
        r'(?:^|\n)\s*(?:Final\s+)?[Aa]nswer[:\s]+(.+?)(?:\n|$)',
        r'(?:^|\n)\s*[Tt]he\s+(?:final\s+)?answer\s+is[:\s]+(.+?)(?:\n|$)',
        r'(?:^|\n)\s*[Rr]esult[:\s]+(.+?)(?:\n|$)',
        r'(?:^|\n)\s*[Ss]olution[:\s]+(.+?)(?:\n|$)',
        r'\*\*[Aa]nswer\*\*[:\s]+(.+?)(?:\n|$)',
        r'\*\*[Ff]inal\s+[Aa]nswer\*\*[:\s]+(.+?)(?:\n|$)',
    ]
    
    for pattern in explicit_answer_patterns:
        matches = re.findall(pattern, text, re.MULTILINE | re.IGNORECASE)
        if matches:
            # Return last match (usually the latest answer)
            answer = matches[-1].strip()
            # Clean answer: remove markdown format, extra spaces, etc.
            answer = re.sub(r'\*\*|__|`', '', answer)  # Remove markdown format
            answer = answer.strip()
            if answer and len(answer) < 500:  # Limit answer length
                return answer
    
    # Try to extract from last few lines (usually answer is at the end)
    lines = text.split('\n')
    for line in reversed(lines[-10:]):  # Check last 10 lines
        line = line.strip()
        if line and len(line) > 0:
            # Skip obvious intermediate step markers and questions
            skip_markers = ['step', 'calculation', 'reasoning', 'analysis', 'question', 
                          'task', 'problem', 'solve', 'find', 'please', 'instruction']
            if any(marker in line.lower() for marker in skip_markers):
                continue
            
            # If line is not too long and looks like an answer, return it
            if len(line) < 300 and not line.startswith('#'):
                # Remove markdown format
                clean_line = re.sub(r'\*\*|__|`|#', '', line).strip()
                if clean_line:
                    return clean_line
    
    # If not found in last few lines, try searching entire text for answer patterns
    answer_patterns = [
        r'[Ff]inal answer[:\s]+(.+?)(?:\n|$)',
        r'[Aa]nswer[:\s]+(.+?)(?:\n|$)',
        r'[Tt]he answer is[:\s]+(.+?)(?:\n|$)',
        r'[Rr]esult[:\s]+(.+?)(?:\n|$)',
        r'[Ss]olution[:\s]+(.+?)(?:\n|$)',
    ]
    
    for pattern in answer_patterns:
        matches = re.findall(pattern, text, re.MULTILINE)
        if matches:
            # Return last match (usually the latest answer)
            answer = matches[-1].strip()
            if answer and len(answer) < 1000:  # Limit answer length
                return answer
    
    # If nothing found, return last non-empty line (might be answer)
    for line in reversed(lines):
        line = line.strip()
        if line and len(line) < 500:
            # Skip obvious intermediate steps
            if not any(marker in line.lower() for marker in ['step', 'calculation', 'reasoning', 'analysis', 'question']):
                return line
    
    return None


def normalize_answer(answer: str) -> str:
    """
    Normalize answer format (remove extra spaces, punctuation, etc.).
    
    Args:
        answer: Original answer.
    
    Returns:
        Normalized answer.
    """
    if not answer:
        return ""
    
    # Remove leading and trailing whitespace
    answer = answer.strip()
    
    # Remove common answer marker prefixes
    prefixes = [
        r'^[Ff]inal answer[:\s]+',
        r'^[Aa]nswer[:\s]+',
        r'^[Tt]he answer is[:\s]+',
        r'^[Rr]esult[:\s]+',
        r'^[Ss]olution[:\s]+',
    ]
    for prefix in prefixes:
        answer = re.sub(prefix, '', answer)
    
    answer = answer.strip()
    
    # Remove quotes
    if (answer.startswith('"') and answer.endswith('"')) or \
       (answer.startswith("'") and answer.endswith("'")):
        answer = answer[1:-1].strip()
    
    return answer


def extract_answer_from_camel_result(result: Dict[str, Any]) -> Optional[str]:
    """
    Extract GAIA answer from CAMEL workflow result.
    
    Args:
        result: CAMEL workflow output result.
    
    Returns:
        Extracted answer string, or None if not found.
    """
    # Get conversation result
    conversation_result = result.get("conversation_result", {})
    
    # Try to extract from final message
    final_assistant_message = conversation_result.get("final_assistant_message", "")
    if final_assistant_message:
        answer = extract_answer_from_text(final_assistant_message)
        if answer:
            return normalize_answer(answer)
    
    # Try to extract from conversation history
    conversation_history = conversation_result.get("conversation_history", [])
    
    # Search from back to front (latest messages first)
    for msg in reversed(conversation_history):
        if msg.get("role") == "AI Assistant":
            content = msg.get("content", "")
            if content:
                answer = extract_answer_from_text(content)
                if answer:
                    return normalize_answer(answer)
    
    # If not in conversation history, try searching entire result dictionary
    result_str = json.dumps(result, ensure_ascii=False)
    answer = extract_answer_from_text(result_str)
    if answer:
        return normalize_answer(answer)
    
    return None


def compare_answers(predicted: str, correct: str, tolerance: float = 0.01) -> bool:
    """
    Compare predicted answer and correct answer to see if they match.
    
    Args:
        predicted: Predicted answer.
        correct: Correct answer.
        tolerance: Tolerance for numerical comparison (only for numerical answers).
    
    Returns:
        Whether they match.
    """
    if not predicted or not correct:
        return False
    
    predicted = normalize_answer(predicted)
    correct = normalize_answer(correct)
    
    # Exact match
    if predicted.lower() == correct.lower():
        return True
    
    # Try numerical comparison
    try:
        pred_num = float(predicted.replace(',', '').replace(' ', ''))
        corr_num = float(correct.replace(',', '').replace(' ', ''))
        if abs(pred_num - corr_num) <= tolerance * max(abs(pred_num), abs(corr_num), 1):
            return True
    except (ValueError, AttributeError):
        pass
    
    # Partial match (predicted answer contains correct answer or vice versa)
    if correct.lower() in predicted.lower() or predicted.lower() in correct.lower():
        return True
    
    # Compare after removing spaces and punctuation
    pred_clean = re.sub(r'[^\w]', '', predicted.lower())
    corr_clean = re.sub(r'[^\w]', '', correct.lower())
    if pred_clean == corr_clean:
        return True
    
    return False

