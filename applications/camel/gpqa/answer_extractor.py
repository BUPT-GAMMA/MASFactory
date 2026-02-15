"""Extract GPQA answers from CAMEL conversation results."""

import re
import json
from typing import Dict, Any, Optional


def extract_answer_from_text(text: str) -> Optional[str]:
    """
    Extract answer from text (A/B/C/D).
    Prioritize finding standalone line answer format.
    
    Args:
        text: Text containing answer.
    
    Returns:
        Extracted answer (A/B/C/D), or None if not found.
    """
    if not isinstance(text, str):
        text = str(text)
    
    # First try to find standalone line answer (highest priority)
    # Match standalone line answers like "A" or "Answer: A"
    lines = text.split('\n')
    # Search from back to front (last few lines more likely to be answer)
    for line in reversed(lines[-10:]):  # Check last 10 lines
        line = line.strip()
        # Match standalone line answer format
        standalone_patterns = [
            r'^([A-D])$',  # Standalone line with only letter "A"
            r'^[Aa]nswer:\s*([A-D])$',  # "Answer: A"
            r'^[Tt]he correct answer is\s*\(?([A-D])\)?$',  # "The correct answer is (A)" or "The correct answer is A"
            r'^[Cc]orrect answer:\s*\(?([A-D])\)?$',  # "Correct answer: (A)"
            r'^[Ff]inal answer:\s*\(?([A-D])\)?$',  # "Final answer: (A)"
            r'^[Aa]nswer is\s*\(?([A-D])\)?$',  # "Answer is (A)"
        ]
        for pattern in standalone_patterns:
            match = re.match(pattern, line)
            if match:
                answer = match.group(1).upper()
                if answer in ['A', 'B', 'C', 'D']:
                    return answer
    
    # If standalone line not found, use original pattern matching (supports more formats)
    patterns = [
        # Formats with parentheses
        r'[Tt]he correct answer is\s*\(([A-D])\)',  # "The correct answer is (A)"
        r'[Cc]orrect answer is\s*\(([A-D])\)',  # "Correct answer is (A)"
        r'[Aa]nswer:\s*\(([A-D])\)',  # "Answer: (A)"
        r'[Aa]nswer is\s*\(([A-D])\)',  # "Answer is (A)"
        r'[Cc]orrect answer:\s*\(([A-D])\)',  # "Correct answer: (A)"
        r'[Ff]inal answer:\s*\(([A-D])\)',  # "Final answer: (A)"
        r'[Cc]hoice\s*\(([A-D])\)',  # "Choice (A)"
        # Formats without parentheses but with colon
        r'[Tt]he correct answer is:\s*([A-D])\b',  # "The correct answer is: A"
        r'[Cc]orrect answer is:\s*([A-D])\b',  # "Correct answer is: A"
        r'[Aa]nswer:\s*([A-D])\b',  # "Answer: A"
        r'[Ff]inal answer:\s*([A-D])\b',  # "Final answer: A"
        # Formats with asterisks (markdown format)
        r'\*\*([A-D])\*\*',  # "**A**"
        r'\*\*([A-D])\)',  # "**A)**"
        r'\*\*([A-D])\s*\)',  # "**A )**"
        r'\(([A-D])\)\s*\*\*',  # "(A)**"
        # Formats with parentheses and colon
        r'\(([A-D])\)\s*[:\-]',  # "(A):" or "(A)-"
        r'([A-D])\s*\)',  # "A)" or "C) Paris"
        r'([A-D])\s*\)\s*\*\*',  # "C)**"
        # Simple parentheses format
        r'\(([A-D])\)',  # "(A)"
        # Final attempt: standalone letter (but needs context confirmation)
        r'\b([A-D])\b',  # Standalone letter A/B/C/D
    ]
    
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            answer = match.group(1).upper()
            if answer in ['A', 'B', 'C', 'D']:
                return answer
    
    return None


def extract_answer_by_value_matching(text: str, choice1: str, choice2: str, choice3: str, choice4: str) -> Optional[str]:
    """
    Infer answer by matching calculation results with option content.
    
    Args:
        text: Assistant message text.
        choice1-4: Four option texts.
    
    Returns:
        Inferred answer (A/B/C/D), or None if cannot infer.
    """
    import re
    
    # Extract key numerical values or text from options
    choices = [
        (choice1, 'A'),
        (choice2, 'B'),
        (choice3, 'C'),
        (choice4, 'D')
    ]
    
    # For numerical options, try to match numerical values
    for choice_text, letter in choices:
        if not choice_text:
            continue
        
        # Extract numerical values from option (including scientific notation)
        # Match like "3 pc", "0.4", "1.5*10^46", "~ 0.7", etc.
        numbers_in_choice = re.findall(r'[\d.]+(?:\*10[^\d]*\d+)?|[\d.]+', choice_text)
        
        for num_str in numbers_in_choice:
            # Clean numerical string
            num_str = num_str.replace('*10', '').replace('^', '').strip()
            if num_str:
                # Search for this value in text (allow some format variations)
                # Match "3", "3.0", "3 pc", "~3", etc.
                pattern = rf'\b{re.escape(num_str)}\b|{re.escape(num_str)}\s*(?:pc|°|GeV|erg/s)?'
                if re.search(pattern, text, re.IGNORECASE):
                    return letter
        
        # For text options, check if key parts of option are mentioned in message
        # Extract first few keywords from option
        key_words = re.findall(r'\b\w+\b', choice_text[:50])
        if len(key_words) >= 2:
            # If multiple keywords from option are in message, might be this option
            matches = sum(1 for word in key_words[:3] if len(word) > 3 and word.lower() in text.lower())
            if matches >= 2:
                return letter
    
    return None


def extract_answer_from_camel_result(result: Dict[str, Any], choice1: str = None, choice2: str = None, 
                                     choice3: str = None, choice4: str = None) -> Optional[str]:
    """
    Extract GPQA answer from CAMEL workflow result.
    
    Args:
        result: CAMEL workflow output result.
        choice1-4: Optional option texts for value matching.
    
    Returns:
        Extracted answer (A/B/C/D), or None if not found.
    """
    # Get conversation result
    conversation_result = result.get("conversation_result", {})
    
    # Try to extract from final message
    final_assistant_message = conversation_result.get("final_assistant_message", "")
    if final_assistant_message:
        answer = extract_answer_from_text(final_assistant_message)
        if answer:
            return answer
        
        # If direct extraction fails, try value matching
        if choice1 and choice2 and choice3 and choice4:
            answer = extract_answer_by_value_matching(
                final_assistant_message, choice1, choice2, choice3, choice4
            )
            if answer:
                return answer
    
    # Try to extract from conversation history
    conversation_history = conversation_result.get("conversation_history", [])
    
    # Search from back to front (newest messages first)
    for msg in reversed(conversation_history):
        if msg.get("role") == "AI Assistant":
            content = msg.get("content", "")
            if content:
                answer = extract_answer_from_text(content)
                if answer:
                    return answer
                
                # If direct extraction fails, try value matching
                if choice1 and choice2 and choice3 and choice4:
                    answer = extract_answer_by_value_matching(
                        content, choice1, choice2, choice3, choice4
                    )
                    if answer:
                        return answer
    
    # If not in conversation history, try searching entire result dictionary
    result_str = json.dumps(result, ensure_ascii=False)
    answer = extract_answer_from_text(result_str)
    if answer:
        return answer
    
    return None

