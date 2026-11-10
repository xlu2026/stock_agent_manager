# tools/ 说明

这些脚本是**开发/构建期**用的，不是运行时依赖。Agent 跑起来时不会调用它们。

| 脚本 | 用途 | 什么时候跑 |
|---|---|---|
| `gen_sample_data.py` | 用固定种子生成 `quant/data/prices.csv` + `manifest.json`（含 sha256） | 需要重建数据快照时 |
| `build_cordis.py` | 从 `cordis/prompts/*.md` 生成 `cordis/profiles/*.yml` 与 `cordis/phase1-presets.yml` | 改过提示词之后 |
| `install_dsh_profile.py` | 把生成的 profile patch 安装到 `~/.dsh/profiles/{quant,writing}` | 生成之后，或换机器时 |
| `asar_tool.py` | 读 Electron `app.asar`：列文件、取文件内容 | 想确认 DSH 某个插件的真实配置契约时 |
| `extract_dsh.py` | 用上面的读取器批量导出指定插件源码到 `.probe/dsh_src` | 同上，需要读多个文件时 |

`asar_tool.py` 里写死了本机 DSH 的安装路径；换机器时要改 `ASAR` 常量。
`extract_dsh.py` 依赖 `.probe/` 目录，产物只用于排查，不参与构建。

典型顺序：

```powershell
python tools\gen_sample_data.py          # 仅在需要重建数据时
python tools\build_cordis.py             # 改过 cordis/prompts/*.md 之后
python tools\install_dsh_profile.py      # 生成之后
dsh --profile quant --dump-config        # 验证组合是否成立
```
