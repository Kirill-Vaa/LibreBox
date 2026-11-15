# Coding Conventions

These conventions cover the Python code in this repository. Apply them to new code and to the code you change for the current task. The file-ending rule applies to every file in the repository.

- End `.py` files with exactly one trailing newline. End all other files without a trailing newline, so their last line has content.

## General
- Rename identifiers and change signatures when that makes the code clearer within the current task.
- Use async/await by default. Write synchronous code only for CPU-bound work or where async gives no benefit.
- Use one library per purpose. If the project already uses `httpx`, don't add `aiohttp` for the same job.

## Naming
- Spell words out: `message`, `response`, `request`, `value`, `error`, `element` instead of `msg`, `res`, `resp`, `req`, `val`, `e`, `el`. Instead of placeholder names such as `obj`, `var`, `tmp`, `arr`, name what the value holds.
- Name loop variables after the item, for example `for order in orders`. Single letters are fine only for simple numeric ranges such as `for i in range(count)`.
- Start boolean names with `is_`, `has_`, `should_`, `can_`, or a similar prefix.

## Ordering
- Place a new element (function, method, field, import, config key, enum member) where it belongs in the existing order of similar elements, not at the end of the file or block.
- If similar elements have no clear order, choose a logical one, such as by execution flow, by importance, or alphabetically. Place the new element according to that order.
- Keep related declarations and their uses in the same order. If handlers are registered as A, B, C, define them as A, B, C.
- Put parameters and fields without defaults before those with defaults, wherever Python syntax and the framework allow it.

## Formatting
- Use double quotes. Use single quotes only when the string contains a double quote.
- Use f-strings for interpolation instead of `.format()`, `%`, `string.Template`, or `+` concatenation.
- Use triple-quoted strings only for large blocks of text and aiogram message texts.
- Keep each string as one literal on one line, even past the line length. Don't split it like `("..."` / `"...")`.
- Keep a statement on one line when it stays readable and fits the line length.
- Minimize the use of `;`. Don't join several statements on one line with it, write each statement on its own line.
- Write each `from module import a, b, c` on a single line, even when it exceeds the line length. Only `__init__.py` may use multi-line grouped imports.
- Leave two blank lines after the import block.
- Don't add comments or docstrings. Express intent through names instead. Keep existing comments and docstrings, and update or remove any that your change makes inaccurate.

## Errors and Logging
- Catch the specific exception types you expect. Use `except Exception` only at a top-level boundary or as a final fallback that handles or reports unexpected failures.
- Name a bound exception `error` when there is a single handler or the handler catches `Exception`. With several handlers, name each one after its type: `value_error`, `timeout_error`, `key_error`.
- Write log messages in English as a single f-string with no trailing period. Include context that locates the problem, such as an ID, a path, or the operation name: `logger.warning(f"Failed to send message to user {user_id}: {error}")`.
- Choose the level by severity: `debug` for diagnostics, `info` for normal events, `warning` for recoverable issues, `error` for failed operations, and `exception` inside an `except` block when the traceback is needed.