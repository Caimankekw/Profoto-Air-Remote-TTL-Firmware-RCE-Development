# Shared offline helpers / 共享离线工具

`container.py` and `reference_codec.py` are unchanged copies of the project's
authored C11 parser/codec, by Caimankekw, under AGPL-3.0-only. Only the generic
`HexImage` parser and the bounded address-indexed codec are used for these ports.
The C11-only `Container` and C11 image decoder are not used to package N/S/F/O.
The codec table and its pinned manifest are in `../reference/`.

这两个 Python 文件是项目既有 C11 解析与编码工具的原样副本，由 Caimankekw
编写，采用 AGPL-3.0-only。多卡口移植只调用通用 `HexImage` 解析器和有地址
范围限制的编码器；不会用 C11 专用容器或整机镜像解码器封装 N/S/F/O。
编码参数表与固定指纹清单位于 `../reference/`。这些工具不包含 HSS 补丁，
不会运行更新器或访问 USB。
