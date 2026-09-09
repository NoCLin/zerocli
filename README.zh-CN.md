# zerocli

[English](README.md) | [简体中文](README.zh-CN.md)

`zerocli` 是一个面向小型 Python 脚本和 AI Agent Skill 的单文件、纯标准库、类型提示驱动的 CLI 辅助框架。

完整运行时只有 [`zerocli.py`](zerocli.py) 一个文件，支持 Python 3.10+，运行和测试均不依赖任何第三方包。只需将它复制到 Skill 脚本旁边即可完成集成：

```bash
cp zerocli.py path/to/skill/scripts/zerocli.py
```

除下文介绍的受控 `App(CommandClass)` 模式外，只有显式注册的函数才会成为 CLI 入口。`zerocli` 不会检查模块、任意对象或命令返回值。

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

## 使用类组织命令

将无参构造的类直接传给 `App`，即可把它的公开方法变成平铺命令：

```python
from zerocli import App

class Calculator:
    """计算器命令集合。"""

    def __init__(self) -> None:
        self.offset = 1

    def main(self, value: int = 0) -> int:
        """无需子命令即可运行。"""
        return value + self.offset

    def add(self, left: int, right: int) -> int:
        """两数相加，再加上配置的偏移量。"""
        return left + right + self.offset

    def _audit(self) -> None:
        pass  # 私有方法不会暴露。

app = App(Calculator)

if __name__ == "__main__":
    app()
```

```bash
python calculator.py
python calculator.py --value 4
python calculator.py add 10 20
```

`main` 是 class 模式的根回调：只有 `main` 的类就是无子命令应用；`main` 也可以与其他方法命令共存。精确匹配的子命令名称优先于 `main` 参数，与普通根默认回调的规则相同。

`App(CommandClass)` 只暴露直接声明在该类中的公开实例方法。静态方法、类方法、私有方法、继承方法、property、数据属性以及返回对象的成员均不会暴露。snake_case 方法名会转换成 kebab-case 命令名。

构造函数必须不接收任何参数。每次 `app.run(...)` 都会在解析成功后创建新实例；注册和帮助输出不会实例化类。应用名称默认使用类名，类 docstring 用于根帮助，方法 docstring 用于命令帮助。完整可运行版本见 [`examples/classes.py`](examples/classes.py)。

## 嵌套子命令

Group 是通过 `app.group(name)` 或 `group.group(name)` 显式创建的命令命名空间。可执行的 Group 行为及其参数必须放在显式的 `@group.default` 回调中。

```python
from pathlib import Path
from zerocli import App

app = App("files", help="Files Skill 使用的工具")

repo = app.group("repo", help="仓库操作")

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

默认值始终来自 Python 函数签名；`Option` 只提供 CLI 元数据。

## 返回值

- `None` 不输出任何内容。
- `str`、`int`、`float`、`bool`、`Path`、Enum 值和未知对象输出为一行文本。
- `dict`、`list` 和 `tuple` 输出为可读 JSON，并保留 Unicode 字符。
- Dataclass 实例先通过 `dataclasses.asdict()` 转换，再输出为 JSON。
- 嵌套的 Path、Enum 和未知值会被递归规范化。
- 结构化输出是严格 JSON；NaN 和 Infinity 等非有限浮点数会抛出 `ValueError`，不会输出非标准 token。
- 映射键遵循 `json.dumps` 规则，必须是 `str`、`int`、`float`、`bool` 或 `None`。

用户回调抛出的异常会原样向上传播。解析和类型转换错误由 `argparse` 输出到 stderr，并以状态码 2 退出。

## 测试与 CI

测试套件只使用 `unittest`，直接调用 `app.run(argv)`，并为公开的根回调示例加入了 doctest：

```bash
python -m unittest discover -v
```

GitHub Actions 会在 Python 3.10、3.11、3.12、3.13 和 3.14 上运行完整测试及示例命令冒烟测试。

## 限制与非目标

版本 1 会明确拒绝 `*args`、`**kwargs`、仅位置参数、复杂 Union、作为输入注解的映射，以及文档范围外的列表元素类型。命令装饰器必须带括号，包括 `@app.command()`；Group 只使用显式的 `app.group(name)` 形式。它不提供异步分发、Shell 补全、环境变量或配置文件加载、依赖注入、彩色输出、交互模式、任意 Python 字面量解析和隐式别名；不会动态遍历对象，也不宣称兼容 Fire、Typer 或 Click。
