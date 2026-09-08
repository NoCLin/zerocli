# zerocli

[English](README.md) | [简体中文](README.zh-CN.md)

`zerocli` 是一个面向小型 Python 脚本和 AI Agent Skill 的单文件、纯标准库、类型提示驱动的 CLI 辅助框架。

完整运行时只有 [`zerocli.py`](zerocli.py) 一个文件，支持 Python 3.10+，运行和测试均不依赖任何第三方包。只需将它复制到 Skill 脚本旁边即可完成集成：

```bash
cp zerocli.py path/to/skill/scripts/zerocli.py
```

只有显式注册的函数才会成为 CLI 入口；`zerocli` 不会检查或发布模块内其他成员。

## 无子命令脚本

`@app.main` 是根回调的标准写法，`@app.default` 是它的完全等价别名。

```python
from pathlib import Path
from zerocli import App

app = App("wc", help="统计文件行数", version="wc 1.0")

@app.main
def count_lines(path: Path, limit: int | None = None) -> dict:
    """统计 PATH 的行数。"""
    lines = path.read_text(encoding="utf-8").splitlines()
    if limit is not None:
        lines = lines[:limit]
    return {"path": str(path), "lines": len(lines)}

if __name__ == "__main__":
    app()
```

```bash
python wc.py README.md --limit 20
python wc.py --help
python wc.py --version
```

`app.run(argv)` 使用同一套解析逻辑，但不会修改 `sys.argv`。它会返回回调结果，也是测试时推荐使用的 API。

## 平铺子命令

```python
from zerocli import App

app = App("json-tool")

@app.command()
def compact(text: str) -> dict:
    """解析 JSON 文本。"""
    import json
    return json.loads(text)

@app.command("validate")
def check(text: str) -> bool:
    """检查 JSON 文本是否合法。"""
    import json
    json.loads(text)
    return True
```

函数名会从 `snake_case` 自动转换成 `kebab-case`；装饰器中显式提供的名称优先于自动名称。

## 嵌套子命令

Group 是命令命名空间。零参数的 Group 声明函数可以提供文档，但在构建解析器和命令分发期间绝不会被执行。可执行的 Group 行为及其参数必须放在显式的 `@group.default` 回调中。

```python
from pathlib import Path
from zerocli import App

app = App("files", help="Files Skill 使用的工具")

@app.group("repo", help="仓库操作")
def repo():
    """管理仓库文件。"""

@repo.command("find")
def find_files(root: Path, pattern: str = "*.py") -> list[str]:
    """在 ROOT 下查找匹配文件。"""
    return [str(path) for path in root.rglob(pattern)]

git = repo.group("git", help="Git 相关操作")

@git.command("status")
def status(short: bool = False) -> str:
    """显示仓库状态。"""
    return "clean" if short else "working tree clean"

if __name__ == "__main__":
    app()
```

```bash
python files.py repo --help
python files.py repo find . --pattern '*.md'
python files.py repo git --help
python files.py repo git status --short
```

任何没有默认回调的 Group 在未指定子命令时都会输出自身帮助并成功返回，空 Group 也一样。未知子命令使用 `argparse` 的常规错误格式，并以状态码 2 退出。子节点必须直接写在父节点之后；在子节点前放置 `--` 会被拒绝，不会再静默绕过分发。嵌套路由由数据驱动，没有固定深度限制。

也可以使用显式写法 `repo = app.group("repo")`。使用装饰器时，`@app.group()` 会根据声明函数名推导 Group 名称。

### Group 默认回调

Group 可以显式处理未指定子命令时的调用：

```python
repo = app.group("repo")

@repo.default
def repo_summary(verbose: bool = False) -> dict:
    return {"summary": True, "verbose": verbose}

@repo.command("find")
def find(pattern: str = "*.py") -> list[str]:
    return [pattern]
```

`files repo` 和 `files repo --verbose` 会调用默认回调，`files repo find` 则调用子命令。路由会检查 Group 后的第一个 token：如果它与子节点名称完全匹配，则子节点始终优先；否则全部剩余 token 都作为默认回调的参数解析。因此，与子节点同名的值不能作为默认回调在该位置上的位置参数。根默认回调与根子命令使用相同规则。

## 参数映射

| Python 签名 | CLI 形式 |
|---|---|
| `path: Path` | 必填位置参数 `path` |
| `count: int = 3` | `--count INT`，默认值为 `3` |
| `dry_run: bool = False` | `--dry-run` |
| `cache: bool = True` | `--no-cache` |
| `*` 后的 `token: str` | 必填选项 `--token TEXT` |
| `tags: list[str] | None = None` | `--tags TEXT [TEXT ...]` |
| `mode: Mode = Mode.safe` | Enum 选项 `--mode {safe,...}` |

支持的标量注解包括 `str`、`int`、`float`、`bool`、`pathlib.Path` 和 `enum.Enum` 子类，同时支持 `T | None`、`Optional[T]` 以及无注解字符串参数。列表元素可以是 `str`、`int`、`float` 或 `Path`。

必填参数默认映射为位置参数；关键字专用参数或使用 `Option` 标记的参数映射为选项。带默认值的参数默认映射为选项，除非使用 `Argument` 标记。长选项名采用 kebab-case，`--count 3` 和 `--count=3` 均可使用。

长选项必须完整拼写；不接受用 `--max-l` 代替 `--max-lines` 之类的前缀缩写。生成的长选项、短选项、内置帮助 flag 和已配置的根 `--version` 会在注册时检查冲突。短选项由 `-` 加一个非空白 Unicode 字符组成，其中 `-h` 保留给帮助功能。

布尔选项不会消耗后续参数。默认值为 `False` 时生成 `--flag`，默认值为 `True` 时生成 `--no-flag`。省略选项时会精确保留 Python 默认值。布尔参数必须带默认值，因为必填 flag 无法同时表达两个布尔值；必填布尔参数会在注册时被拒绝。

列表只使用一种语法：一个选项后跟连续的多个值，例如 `--tags docs urgent`；位置列表同样接收连续值。可选列表一旦出现就至少需要一个值。当列表选项与必填位置参数可能产生边界歧义时，应将列表选项放在位置参数之后。

### 参数文档

`typing.Annotated` 元数据是可选功能：

```python
from typing import Annotated
from pathlib import Path
from zerocli import Argument, Option

def upload(
    path: Annotated[Path, Argument(help="待上传文件", metavar="FILE")],
    retries: Annotated[int, Option(help="重试次数", short="-r")] = 3,
):
    ...
```

当函数签名没有默认值时，可以使用 `Option(3)` 提供默认值。同时在签名和 `Option()` 中定义默认值会被拒绝。

## 返回值

- `None` 不输出任何内容。
- `str`、`int`、`float`、`bool`、`Path`、Enum 值和未知对象输出为一行文本。
- `dict`、`list` 和 `tuple` 输出为可读 JSON，并保留 Unicode 字符。
- Dataclass 实例先通过 `dataclasses.asdict()` 转换，再输出为 JSON。
- 嵌套的 Path、Enum、未知值和映射键会被递归规范化。
- 结构化输出是严格 JSON；NaN 和 Infinity 等非有限浮点数会抛出 `ValueError`，不会输出非标准 token。

用户回调抛出的异常会原样向上传播。解析和类型转换错误由 `argparse` 输出到 stderr，并以状态码 2 退出。

## 测试与 CI

测试套件只使用 `unittest`，直接调用 `app.run(argv)`，并为公开的根回调示例加入了 doctest：

```bash
python -m unittest discover -v
```

GitHub Actions 会在 Python 3.10、3.11、3.12、3.13 和 3.14 上运行完整测试及示例命令冒烟测试。

## 限制与非目标

版本 1 会明确拒绝 `*args`、`**kwargs`、仅位置参数、复杂 Union、作为输入注解的映射，以及文档范围外的列表元素类型。命令和 Group 装饰器必须带括号，包括空形式 `@app.command()` 和 `@app.group()`。它不提供异步分发、Shell 补全、环境变量或配置文件加载、依赖注入、彩色输出、交互模式、任意 Python 字面量解析和隐式别名；不会动态遍历对象，也不宣称兼容 Fire、Typer 或 Click。
