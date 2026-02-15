from __future__ import annotations

import re

from .base import StatelessFormatter

class MarkdownMessageFormatter(StatelessFormatter):
    """Parse and dump markdown heading-based structured messages."""

    def __init__(self):
        super().__init__()
        self._is_input_formatter = True
        self._is_output_formatter = True
        self._agent_introducer = """
Your response must be formatted in Markdown with clear section headings.
Use # for main sections, ## for subsections, ### for sub-subsections, etc.
Each heading should be followed by its content on subsequent lines.

FORMAT EXAMPLE:
# Section Name
Content for this section goes here.
Can span multiple lines.

## Subsection Name
Subsection content here.

### Sub-subsection
More detailed content.

# Another Section
Another section's content.
"""

    def format(self, message: str) -> dict:
        """Parse markdown text into nested dictionary structure."""

        if isinstance(message, dict):
            return message

        message = message.strip()
        if message.startswith("```markdown") and message.endswith("```"):
            message = message[len("```markdown") :].strip()
            if message.endswith("```"):
                message = message[:-3].strip()
        elif message.startswith("```") and message.endswith("```"):
            first_newline = message.find("\n")
            if first_newline != -1:
                message = message[first_newline + 1 :].strip()
                if message.endswith("```"):
                    message = message[:-3].strip()

        heading_pattern = re.compile(r"^(#{1,6})\s+(.+)$", re.MULTILINE)
        lines = message.split("\n")

        in_code_block = False
        code_block_lines = set()
        for i, line in enumerate(lines):
            stripped = line.strip()
            if stripped.startswith("```"):
                in_code_block = not in_code_block
                code_block_lines.add(i)
            elif in_code_block:
                code_block_lines.add(i)

        headings = []
        for i, line in enumerate(lines):
            if i in code_block_lines:
                continue
            match = heading_pattern.match(line.strip())
            if match:
                level = len(match.group(1))
                title = match.group(2).strip()
                headings.append((level, title, i))

        if not headings:
            import json

            content = message.strip()
            if content.startswith("```json") and content.endswith("```"):
                content = content[7:].strip()
                if content.endswith("```"):
                    content = content[:-3].strip()
            elif content.startswith("```") and content.endswith("```"):
                first_newline = content.find("\n")
                if first_newline != -1:
                    content = content[first_newline + 1 :].strip()
                    if content.endswith("```"):
                        content = content[:-3].strip()
            try:
                json_start = content.find("{")
                json_end = content.rfind("}")
                if json_start != -1 and json_end > json_start:
                    return json.loads(content[json_start : json_end + 1])
            except (json.JSONDecodeError, ValueError):
                pass
            return {"content": message.strip()} if message.strip() else {}

        def get_content_between(start_idx: int, end_idx: int) -> str:
            content_lines = []
            for i in range(start_idx + 1, end_idx):
                line = lines[i]
                if not heading_pattern.match(line.strip()):
                    content_lines.append(line)
            return "\n".join(content_lines).strip()

        def build_nested_dict(heading_list: list, start: int, end: int, max_line: int) -> dict:

            result = {}
            i = start

            while i < end:
                level, title, line_idx = heading_list[i]

                next_same_or_higher = end
                for j in range(i + 1, end):
                    next_level = heading_list[j][0]
                    if next_level <= level:
                        next_same_or_higher = j
                        break

                if next_same_or_higher < end:
                    section_max_line = heading_list[next_same_or_higher][2]
                else:
                    section_max_line = max_line

                children_start = i + 1
                children_end = next_same_or_higher

                has_children = children_start < children_end

                if has_children:
                    first_child_line = heading_list[children_start][2]
                    direct_content = get_content_between(line_idx, first_child_line)

                    children_dict = build_nested_dict(
                        heading_list, children_start, children_end, section_max_line
                    )

                    if direct_content:
                        result[title] = {"_content": direct_content, **children_dict}
                    else:
                        result[title] = children_dict
                else:
                    content = get_content_between(line_idx, section_max_line)
                    result[title] = content

                i = next_same_or_higher

            return result

        result = build_nested_dict(headings, 0, len(headings), len(lines))

        # if len(result) == 1:
        #     single_key = list(result.keys())[0]
        #     single_value = result[single_key]
        #     if isinstance(single_value, dict) and single_value:
        #         result = single_value

        return result

    def dump(self, message: dict, _level: int = 1) -> str:
        """Dump nested dictionary into markdown heading text."""

        if isinstance(message, str):
            return message

        result_lines = []
        heading_prefix = "#" * _level

        for key, value in message.items():
            if key == "_content":
                continue

            result_lines.append(f"{heading_prefix} {key}")

            if isinstance(value, dict):
                if "_content" in value:
                    result_lines.append(value["_content"])
                    result_lines.append("")

                sub_content = self.dump(value, _level + 1)
                if sub_content:
                    result_lines.append(sub_content)
            elif value:
                result_lines.append(str(value))
                result_lines.append("")

        return "\n".join(result_lines).strip()
