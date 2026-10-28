"""Platform and service blueprint registry."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from flask import Flask


@dataclass
class PlatformSpec:
    id: str
    name: str
    register: Callable[[Flask], None]
    modes: frozenset[str] = field(default_factory=lambda: frozenset({"full"}))
    enabled_labels: list[str] = field(default_factory=list)


class PlatformRegistry:
    def __init__(self):
        self._platforms: dict[str, PlatformSpec] = {}

    def add(self, spec: PlatformSpec) -> None:
        self._platforms[spec.id] = spec

    def register_all(self, app: Flask, mode: str = "full") -> list[str]:
        enabled: list[str] = []
        for spec in self._platforms.values():
            if mode in spec.modes or (mode == "full" and "full" in spec.modes):
                spec.register(app)
                enabled.append(spec.id)
        return enabled

    def list_for_mode(self, mode: str) -> list[PlatformSpec]:
        return [
            s for s in self._platforms.values()
            if mode in s.modes or (mode == "full" and "full" in s.modes)
        ]


def build_default_registry() -> PlatformRegistry:
    from parse_tools.platforms import bilibili, channels, douyin, kuaishou, wechat, xiaohongshu
    from parse_tools.services import proxy as proxy_svc
    from parse_tools.services import transcode, updater, waterwall

    registry = PlatformRegistry()

    registry.add(PlatformSpec(
        id="wechat",
        name="微信公众号",
        register=wechat.register,
        modes=frozenset({"full", "mp"}),
        enabled_labels=[
            "公众号登录（微信读书扫码）",
            "公众号账号与文章列表",
            "文章下载 / 导出（HTML / Markdown / PDF）",
            "RSS 订阅与定时增量抓取",
        ],
    ))
    registry.add(PlatformSpec(
        id="proxy",
        name="代理",
        register=proxy_svc.register,
        modes=frozenset({"full", "mp"}),
        enabled_labels=["代理配置"],
    ))
    registry.add(PlatformSpec(
        id="douyin",
        name="抖音",
        register=douyin.register,
        modes=frozenset({"full"}),
    ))
    registry.add(PlatformSpec(
        id="kuaishou",
        name="快手",
        register=kuaishou.register,
        modes=frozenset({"full"}),
    ))
    registry.add(PlatformSpec(
        id="channels",
        name="微信视频号",
        register=channels.register,
        modes=frozenset({"full"}),
    ))
    registry.add(PlatformSpec(
        id="xiaohongshu",
        name="小红书",
        register=xiaohongshu.register,
        modes=frozenset({"full"}),
    ))
    registry.add(PlatformSpec(
        id="bilibili",
        name="哔哩哔哩",
        register=bilibili.register,
        modes=frozenset({"full"}),
    ))
    registry.add(PlatformSpec(
        id="transcode",
        name="转码",
        register=transcode.register,
        modes=frozenset({"full"}),
    ))
    registry.add(PlatformSpec(
        id="updater",
        name="更新",
        register=updater.register,
        modes=frozenset({"full"}),
    ))
    registry.add(PlatformSpec(
        id="waterwall",
        name="防水墙",
        register=waterwall.register,
        modes=frozenset({"full"}),
    ))
    return registry
