# Coding Conventions

Apply these conventions to code you write or change. End every `.py` file you create or edit with exactly one trailing newline, and every other file with no trailing newline.

## General
- Rename identifiers and change signatures when it makes the code clearer within the task's scope.
- Default to async/await. Write synchronous code only for CPU-bound work or where async gives no benefit.
- Use one library per purpose. Don't add `aiohttp` when the project already uses `httpx`.

## Naming
- Spell words out: `message`, `response`, `request`, `value`, `element`, not `msg`, `resp`, `req`, `val`, `el`. Name a value after what it holds, not `obj`, `var`, `tmp`, `arr`.
- Name loop variables after the item (`for order in orders`). Use single letters only for simple numeric ranges.
- Prefix boolean names with `is_`, `has_`, `should_`, `can_`, or similar.

## Ordering
- Insert a new function, method, field, import, config key, or enum member where it fits the existing order of similar elements, instead of appending it at the end. If there is no clear order, follow a logical one: execution flow, importance, or alphabetical.
- Keep declarations in the same order as their uses: handlers registered as A, B, C are defined as A, B, C.
- Put parameters and fields without defaults before those with defaults, even where Python doesn't enforce it, as with keyword-only parameters and model fields.

## Formatting
- Use double quotes. Use single quotes only when the string contains a double quote.
- Interpolate with f-strings, not `.format()`, `%`, or `+`.
- Use triple-quoted strings only for large blocks of text and aiogram message texts.
- Keep a statement on one line when it fits the line length and stays readable. Don't join statements with `;`.
- Keep each string as a single literal and each `from module import a, b, c` on a single line, even past the line length. Only `__init__.py` may use multi-line grouped imports.
- Leave two blank lines after the import block.
- Don't add comments or docstrings. Let names carry the intent. Keep existing ones, and update or remove any that your change makes inaccurate.

## Errors and Logging
- Catch specific exceptions. Use `except Exception` only at a top-level boundary or as a final fallback that handles or reports the failure.
- Name a caught exception `error`. When a `try` has several handlers, name the specific ones after their type (`value_error`, `timeout_error`) and keep `error` for `except Exception`.
- Write log messages in English as one f-string with no trailing period. Include context that locates the problem, such as an ID, a path, or the operation: `logger.warning(f"Failed to send message to user {user_id}: {error}")`.

## README and Commits
- When you change behavior, configuration, commands, or environment variables, update README.md in the same task if the change affects it. If it doesn't, say so in one line of your final message.
- Write a commit message as one Conventional Commits subject line in lowercase imperative, such as `feat(config): add REDIS_URL setting`, matching the style and language of `git log`. Give one message, not several options. Add a body only when asked.