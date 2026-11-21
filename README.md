# audio-midi-quantize

## 题面

MIDI 一键量化后，摇摆感全没了、和弦还粘在一起：swing 使奇数位后移，反拍全部错位；snap 直接取最近格、忽略 strength，拖一半和拖满没有区别；量化后不排序，时间线乱成一团；重叠只警告不裁剪，同拍和弦被合并；力度分层用线性刻度，强弱动态被压平；网格点不含终点，最后一拍丢失；division 不整除 ppq 却不报错，网格从根上错位；swing 超过 1 不钳制，偏移量超过一整格；批量量化让所有轨道共用一张网格，轨与轨之间互相串音；ppq<=0 不校验，直接除零。quantize/grid.py 是核心，tests/test_grid.py 15个红。要修的是：让 swing 只把偶数位后移并钳制到 [0,1]，让 snap 按 strength 插值，量化后按 tick 稳定排序，重叠按 min_gap 裁剪且保留和弦，力度按几何曲线分层，网格补上 ppq 终点，validate 报告 division 不整除 ppq，批量按轨独立建网格并整体回滚，以及所有 ppq<=0 的入口都抛 QuantizeError。

## 运行方式

在仓库根目录执行：

```bash
python -m pytest tests -q
```

初始（未修复）状态必须恰好 15 个测试失败，不能出现 collection、import 或 syntax error：

```text
15 failed
```

修复 `quantize/grid.py` 后应得到 `15 passed`。测试只依赖 Python 标准库与 pytest，离线运行，不使用随机数，也不 sleep。

## 字段表

| 字段 | 取值 |
| --- | --- |
| 所属领域 | 游戏、图形与多媒体 |
| 子方向 | 音视频处理 |
| 任务类型 | Bugfix |
| 语言/框架 | Python 3, pytest |
| 环境可复现等级 | 无外部依赖 |

## 评测约束

`tests/test_grid.py` 是评测用例，不可修改；需要修复的是 `quantize/grid.py` 中的 8 个桩函数。所有音符统一使用 `{"tick", "dur", "vel"}` 字段，坐标单位为整数 tick。
