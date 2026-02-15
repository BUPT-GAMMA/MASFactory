"""Extract MMLU-Pro answers from CAMEL conversation results (10 options A-J)."""

import re
import json
from typing import Dict, Any, Optional


def extract_answer_from_text(text: str) -> Optional[str]:
    """
    Extract answer from text (A-J, total 10 options).
    Prioritize finding standalone line answer format.
    
    Args:
        text: Text containing answer.
    
    Returns:
        Extracted answer (A-J), or None if not found.
    """
    if not isinstance(text, str):
        text = str(text)
    
    # MMLU-Pro has 10 options: A-J
    valid_answers = ['A', 'B', 'C', 'D', 'E', 'F', 'G', 'H', 'I', 'J']
    
    # First try to find "Final answer: X" format (highest priority, this is standard format)
    final_answer_pattern = r'[Ff]inal answer:\s*([A-J])\b'
    final_answer_matches = list(re.finditer(final_answer_pattern, text))
    if final_answer_matches:
        # Take last match (usually final answer)
        last_match = final_answer_matches[-1]
        answer = last_match.group(1).upper()
        if answer in valid_answers:
            return answer
    
    # Then try to find "Option X" format (second priority, usually in conclusion)
    option_pattern = r'[Oo]ption\s*\(?([A-J])\)?'
    option_matches = list(re.finditer(option_pattern, text))
    if option_matches:
        # Take last match (usually final answer)
        last_match = option_matches[-1]
        answer = last_match.group(1).upper()
        if answer in valid_answers:
            return answer
    
    # Then try to find standalone line answer (second priority)
    # Match standalone line answers like "A" or "Answer: A"
    lines = text.split('\n')
    # Search from back to front (last few lines more likely to be answer)
    for line in reversed(lines[-10:]):  # Check last 10 lines
        line = line.strip()
        # Match standalone line answer format
        standalone_patterns = [
            r'^([A-J])$',  # Standalone line with only letter "A" to "J"
            r'^[Aa]nswer:\s*([A-J])$',  # "Answer: A"
            r'^[Tt]he correct answer is\s*\(?([A-J])\)?$',  # "The correct answer is (A)" or "The correct answer is A"
            r'^[Cc]orrect answer:\s*\(?([A-J])\)?$',  # "Correct answer: (A)"
            r'^[Ff]inal answer:\s*\(?([A-J])\)?$',  # "Final answer: (A)"
            r'^[Aa]nswer is\s*\(?([A-J])\)?$',  # "Answer is (A)"
        ]
        for pattern in standalone_patterns:
            match = re.match(pattern, line)
            if match:
                answer = match.group(1).upper()
                if answer in valid_answers:
                    return answer
    
    # If standalone line not found, use original pattern matching (supports more formats)
    # Sorted by priority, search from back to front (last occurrence more likely to be answer)
    patterns = [
        # Formats with parentheses (high priority)
        r'[Tt]he correct answer is\s*\(([A-J])\)',  # "The correct answer is (A)"
        r'[Cc]orrect answer is\s*\(([A-J])\)',  # "Correct answer is (A)"
        r'[Ff]inal answer:\s*\(([A-J])\)',  # "Final answer: (A)"
        r'[Aa]nswer:\s*\(([A-J])\)',  # "Answer: (A)"
        r'[Aa]nswer is\s*\(([A-J])\)',  # "Answer is (A)"
        r'[Cc]orrect answer:\s*\(([A-J])\)',  # "Correct answer: (A)"
        # Formats without parentheses but with colon
        r'[Tt]he correct answer is:\s*([A-J])\b',  # "The correct answer is: A"
        r'[Cc]orrect answer is:\s*([A-J])\b',  # "Correct answer is: A"
        r'[Ff]inal answer:\s*([A-J])\b',  # "Final answer: A"
        r'[Aa]nswer:\s*([A-J])\b',  # "Answer: A"
        # Formats with asterisks (markdown format, usually in conclusion)
        r'\*\*[Oo]ption\s*\(?([A-J])\)?\*\*',  # "**Option C**"
        r'\*\*([A-J])\*\*',  # "**A**"
        r'\*\*([A-J])\)',  # "**A)**"
        r'\*\*([A-J])\s*\)',  # "**A )**"
        r'\(([A-J])\)\s*\*\*',  # "(A)**"
        # Other formats
        r'[Cc]hoice\s*\(([A-J])\)',  # "Choice (A)"
        r'\(([A-J])\)\s*[:\-]',  # "(A):" or "(A)-"
        r'([A-J])\s*\)\s*\*\*',  # "C)**"
        r'([A-J])\s*\)',  # "A)" or "C) Paris"
        # Simple parentheses format
        r'\(([A-J])\)',  # "(A)"
    ]
    
    # Search all matches from back to front, take last one (most likely to be final answer)
    all_matches = []
    for pattern in patterns:
        matches = list(re.finditer(pattern, text))
        all_matches.extend(matches)
    
    if all_matches:
        # Sort by position, take last one
        all_matches.sort(key=lambda m: m.start())
        last_match = all_matches[-1]
        answer = last_match.group(1).upper()
        if answer in valid_answers:
            return answer
    
    # Final attempt: standalone letter (but needs context confirmation, only in last few lines)
    lines = text.split('\n')
    for line in reversed(lines[-5:]):  # Only check last 5 lines
        match = re.search(r'\b([A-J])\b', line)
        if match:
            answer = match.group(1).upper()
            if answer in valid_answers:
                return answer
    
    return None


def extract_answer_by_value_matching(
    text: str,
    choiceA: str, choiceB: str, choiceC: str, choiceD: str,
    choiceE: str, choiceF: str, choiceG: str, choiceH: str,
    choiceI: str, choiceJ: str
) -> Optional[str]:
    """
    Infer answer by matching calculation results with option content.
    
    Args:
        text: Assistant message text.
        choiceA-J: Ten option texts.
    
    Returns:
        Inferred answer (A-J), or None if cannot infer.
    """
    import re
    
    # Extract key numerical values or text from options
    choices = [
        (choiceA, 'A'),
        (choiceB, 'B'),
        (choiceC, 'C'),
        (choiceD, 'D'),
        (choiceE, 'E'),
        (choiceF, 'F'),
        (choiceG, 'G'),
        (choiceH, 'H'),
        (choiceI, 'I'),
        (choiceJ, 'J')
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


def extract_answer_from_camel_result(
    result: Dict[str, Any],
    choiceA: str = None, choiceB: str = None, choiceC: str = None, choiceD: str = None,
    choiceE: str = None, choiceF: str = None, choiceG: str = None, choiceH: str = None,
    choiceI: str = None, choiceJ: str = None
) -> Optional[str]:
    """
    Extract MMLU-Pro answer from CAMEL workflow result.
    
    Args:
        result: CAMEL workflow output result.
        choiceA-J: Optional option texts for value matching.
    
    Returns:
        Extracted answer (A-J), or None if not found.
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
        if all([choiceA, choiceB, choiceC, choiceD, choiceE, choiceF, choiceG, choiceH, choiceI, choiceJ]):
            answer = extract_answer_by_value_matching(
                final_assistant_message,
                choiceA, choiceB, choiceC, choiceD, choiceE, choiceF, choiceG, choiceH, choiceI, choiceJ
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
                if all([choiceA, choiceB, choiceC, choiceD, choiceE, choiceF, choiceG, choiceH, choiceI, choiceJ]):
                    answer = extract_answer_by_value_matching(
                        content,
                        choiceA, choiceB, choiceC, choiceD, choiceE, choiceF, choiceG, choiceH, choiceI, choiceJ
                    )
                    if answer:
                        return answer
    
    # If not in conversation history, try searching entire result dictionary
    result_str = json.dumps(result, ensure_ascii=False)
    answer = extract_answer_from_text(result_str)
    if answer:
        return answer
    
    return None

