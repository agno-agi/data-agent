"""Save verified learnings to knowledge base."""

import json
import time

from agno.knowledge import Knowledge
from agno.knowledge.reader.text_reader import TextReader
from agno.tools import tool
from agno.utils.log import logger


def create_save_learning_tool(knowledge: Knowledge):
    """Create save_learning tool with verification after insert."""

    @tool
    def save_learning(
        title: str,
        learning: str,
        context: str | None = None,
        tags: list[str] | None = None,
    ) -> str:
        """Save a learning to the knowledge base with verification.

        Call after discovering a data gotcha, fixing a type error,
        finding a date format quirk, or when a user corrects you.

        Args:
            title: Short descriptive title (e.g., "position column is TEXT in drivers_championship")
            learning: What you learned and the fix (e.g., "Use position = '1' not position = 1")
            context: Optional context about when/how this was discovered
            tags: Optional tags for categorization (e.g., ["type-gotcha", "drivers_championship"])
        """
        if not title or not title.strip():
            return "Error: Title required."
        if not learning or not learning.strip():
            return "Error: Learning required."

        payload = {
            "type": "learning",
            "title": title.strip(),
            "learning": learning.strip(),
            "context": context.strip() if context else None,
            "tags": tags or [],
        }
        payload = {k: v for k, v in payload.items() if v is not None}

        name = title.strip().lower().replace(" ", "_")[:80]
        text_content = json.dumps(payload, ensure_ascii=False, indent=2)

        max_attempts = 2
        for attempt in range(max_attempts):
            try:
                knowledge.insert(
                    name=name,
                    text_content=text_content,
                    reader=TextReader(),
                    skip_if_exists=True,
                )
            except Exception as e:
                logger.error(f"save_learning insert failed (attempt {attempt + 1}): {e}")
                if attempt < max_attempts - 1:
                    time.sleep(0.5)
                    continue
                return f"Error: Failed to save learning after {max_attempts} attempts: {e}"

            # Verify the learning was actually persisted
            try:
                results = knowledge.search(query=title.strip(), max_results=3)
                if results:
                    for doc in results:
                        if name in (doc.name or ""):
                            logger.info(f"Learning verified: '{title}'")
                            return f"Learning saved and verified: '{title}'"
                # Not found — retry
                logger.warning(f"Learning not found after insert (attempt {attempt + 1})")
                if attempt < max_attempts - 1:
                    time.sleep(0.5)
            except Exception as e:
                logger.error(f"save_learning verification failed: {e}")
                if attempt < max_attempts - 1:
                    time.sleep(0.5)

        return f"Warning: Learning '{title}' was inserted but could not be verified. It may not have persisted."

    return save_learning
