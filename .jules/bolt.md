## 2026-03-01 - Fast parsing using iterative line checking instead of Regex
**Learning:** Compiled regex `.finditer()` for parsing large multiline textual blocks (like subtitle SRT files) can be significantly slower than a direct programmatic iterative string traversal. Profiling revealed that an iterative linear traversal with basic `line.isdigit()` and `-->` checks was 2x faster than searching the entire file directly with `block_pattern_obj.finditer()`, and is safer than rigid string `split('\n\n')` approaches which fail if newline spacing between blocks is inconsistent.
**Action:** When extracting predictable blocks from large text documents, prefer using native programmatic iterative parsing over large complex multi-line regex matchers.
## 2026-03-02 - Object instantiation vs primitive strings in hot paths
**Learning:** Instantiating `Path` objects in Python just to use `.name` inside functions called repeatedly inside tight loops adds measurable performance overhead. Pre-compiling `re` regular expressions into global variables also significantly speeds up function calls compared to calling `re.sub` directly each time.
**Action:** When working on frequently-called string processing functions, prefer native string primitives and `os.path` functions like `os.path.basename` to avoid object instantiation overhead. Always globally pre-compile regexes.
## 2026-07-09 - Avoid redundant file system calls
**Learning:** Codebase performance pattern: Avoid redundant file system calls (like double `stat()` calls) when traversing directories. For example, instead of checking `if path.exists(): mtime = path.stat().st_mtime`, this results in two filesystem calls. The first call `exists()` does a `stat()` under the hood, and the second `stat()` call does it again. Using a `try: mtime = path.stat().st_mtime except OSError: mtime = 0.0` block reduces syscall overhead by half.
**Action:** When accessing file metadata in loops or comprehensions, use `try...except OSError` blocks around `path.stat()` instead of checking `path.exists()` first.
## 2026-07-28 - Optimize directory scanning with os.scandir
**Learning:** Codebase performance pattern: Prefer `os.scandir()` over `os.listdir()` when scanning directories if you also need file attributes like size, type, or modification time. `os.scandir()` returns `os.DirEntry` objects which cache file attributes (like `.stat().st_size`) directly from the OS directory table, thus avoiding redundant `stat()` system calls that `os.path.getsize()` or `os.path.exists()` would otherwise make.
**Action:** When scanning directories to collect file sizes or types, replace `os.listdir()` followed by `os.path.getsize()` with a `with os.scandir() as it:` loop, checking `entry.is_file()` and accessing `entry.stat().st_size`.

## 2024-08-10 - Regex re.DOTALL vs Native String Search
**Learning:** For simple bounding searches in multiline strings (like finding the end of a header with `\n\n` or the boundaries of a YAML frontmatter `\n---`), using native `str.find()` combined with string slicing is significantly faster than using multi-line regular expressions like `re.sub(r"^WEBVTT.*?\n\n", "", text, flags=re.DOTALL)`.
**Action:** Replace `re.sub` and `re.search` with native string `.find()` and slicing when extracting or stripping well-defined blocks (like headers) from the beginning of large strings to optimize parsing hot paths.
## 2026-08-15 - Fast iterable comparison using zip()
**Learning:** Codebase performance pattern: When comparing elements of two iterables sequentially, using the built-in `zip()` function (e.g., `all(p == c for p, c in zip(prev, cur))`) is significantly faster and more pythonic than using manual loop counters (like `enumerate()`) and index lookups (e.g., `prev[i] == cur[i] for i in range(len)`). `zip()` iterates in C, reducing Python loop overhead.
**Action:** Replace list comprehensions or generator expressions that rely on manual index lookups across multiple iterables with the `zip()` function.
## 2026-08-20 - Fast tuple-based str.startswith iteration
**Learning:** Codebase performance pattern: When checking if a string starts with multiple possible prefixes, pass a tuple of strings directly to `str.startswith()` instead of using a Python-level loop or generator expression with `any()`. This avoids generator creation overhead and leverages highly optimized C-level iteration, making it significantly faster (e.g. ~3x faster in synthetic benchmarks).
**Action:** Replace `any(text.startswith(q) for q in prefixes)` with `text.startswith(prefixes)` where `prefixes` is a tuple.
## 2025-02-12 - Optimize simultaneous iteration with `zip`
**Learning:** When comparing elements of two lists simultaneously (e.g. for finding prefix overlap), using `zip(list1, list2)` is significantly faster than using an `enumerate()` loop with manual list indexing and length checks. This is because `zip` iterates and stops at the shortest list natively in C, avoiding Python-level boundary checks and index lookups inside tight loops.
**Action:** Default to `zip` instead of manual index management when processing dual iterables in hot paths.

## 2026-09-08 - Pre-compile Regex in NLP hot paths
**Learning:** Python's `re` module caches compiled regex patterns internally. However, calling functions like `re.sub()` or `re.search()` with inline string patterns repeatedly still incurs significant overhead from cache lookups in tight loops (e.g. text normalization over thousands of subtitle blocks).
**Action:** Always pre-compile `re` module regexes globally for text-processing hot paths to bypass internal cache lookups.
## 2026-10-27 - Pre-compile Regex for str.replace Alternatives
**Learning:** Even simple regex replacements like `re.sub(r"<[^>]+>", "", text)` when called continuously inside inner loops (like stripping HTML from every line of a subtitle file) suffer from `re` module cache lookup overhead. Pre-compiling to a global `_HTML_TAG_PATTERN` avoids this entirely.
**Action:** Always extract and globally pre-compile `re.sub` patterns that are executed inside tight text-processing loops (NLP hot paths) rather than using the inline `re.sub()` function.
## 2026-08-20 - Fast file path categorization and concatenation
**Learning:** Instantiating `pathlib.Path` objects and concatenating paths using the `/` operator inside a tight loop with redundant iterations adds measurable performance overhead. When partitioning lists of file paths based on extensions, replacing multiple list comprehensions containing pathlib `/` division with a single `for` loop and `os.path.join` avoids redundant iterations and minimizes object instantiation overhead, yielding significant speedups.
**Action:** When scanning a directory to categorize files based on string suffixes, use a single `for` loop with `if/elif` blocks and convert the base `Path` to a string once before the loop to use `os.path.join(base_str, f)`.
## 2024-09-17 - Tuple-based suffix matching vs generator loop
**Learning:** Using `endswith` with a tuple of suffixes and exact matching via `in` with a tuple is ~6x faster than evaluating a generator expression with string concatenation inside `any()` for matching cookie domains.
**Action:** Prefer `in` and `.endswith()` with tuples for performance-sensitive string matching rather than loops or generators.
## 2026-11-20 - Fast directory traversal with os.scandir in history logic
**Learning:** Codebase performance pattern: When traversing directories for specific files, replacing `Path.glob()` and `Path.iterdir()` with `os.scandir()` significantly reduces overhead by avoiding redundant filesystem calls and object instantiations, proving up to 3-5x faster during file scans.
**Action:** Replace `Path.glob()` and `Path.iterdir()` with `os.scandir()` for faster directory traversal, especially in performance-sensitive modules like `history.py` which are scanned frequently.

## 2026-10-04 - Pre-compiling Regex in NLP Hot Paths
**Learning:** Python's `re` module caches compiled regex patterns internally, but invoking functions like `re.match()` and `re.search()` directly with string literals inside loops (e.g., iterating through large JSON history objects or processing thousands of subtitle lines) still incurs unnecessary dictionary lookup overhead for the cache.
**Action:** Extract frequently used regular expressions and assign them to module-level global variables via `re.compile()` (e.g., `_PATTERN = re.compile(r"...")`). Use the compiled object's methods (`_PATTERN.match()`, `_PATTERN.search()`) directly to eliminate compilation cache lookup overhead in performance-sensitive sections.

## 2026-11-20 - Fast tuple-based str.startswith iteration in text streams
**Learning:** Codebase performance pattern: When evaluating lines in a large text stream using multiple `str.startswith()` conditions (an `if/elif` chain), wrap the entire chain inside a single `if line.startswith(TUPLE_OF_PREFIXES):` outer check. This natively quickly bypasses non-matching strings in C, avoiding the overhead of evaluating each condition individually for lines that don't match any prefix.
**Action:** Replace sequential `str.startswith()` checks with a single tuple-based `startswith()` check where applicable.
