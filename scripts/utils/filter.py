import re
import fnmatch
from typing import Callable


class Filter:
    @staticmethod
    def compile_patterns(patterns: list[str] | str) -> re.Pattern:
        """
        将 glob pattern 列表编译为正则表达式。
        """
        if isinstance(patterns, str):
            patterns = [patterns]
        regex_patterns = [fnmatch.translate(pattern) for pattern in patterns]
        combined_regex_pattern = '|'.join(f'({pattern})' for pattern in regex_patterns)
        return re.compile(combined_regex_pattern)

    @staticmethod
    def match(filename: str, pattern: re.Pattern) -> bool:
        """
        检查文件名是否匹配正则表达式。
        """
        filename = filename.replace('\\', '/')
        return pattern.match(filename) is not None

    @staticmethod
    def compile(patterns: list[str] | str) -> Callable[[str], bool]:
        """
        编译 glob pattern 列表为一个函数，用于检查文件名是否匹配。
        """
        pattern = Filter.compile_patterns(patterns)
        return lambda filename: Filter.match(filename, pattern)


if __name__ == "__main__":
    patterns = [

    ]
    pattern = Filter.compile_patterns(patterns)
    print(Filter.match("avg/1.mp3", pattern))
    print(Filter.match("bgm/2.mp3", pattern))
    print(Filter.match("se/3.mp3", pattern))
    print(Filter.match("4.mp3", pattern))
