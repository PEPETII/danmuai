# 配置规范化合同

入口为 `app/application/config_service.py:ConfigService._normalize_items`。仅处理允许写入的已有字段；缺失字段不补写，secret 与持久化事务由现有路径负责。普通整数使用同一转换与上下界规则，转换失败使用表内默认值。

| 字段 | 默认 | 最小 | 最大 |
|---|---:|---:|---:|
| `danmu_recent_ttl_sec` | 30 | 1 | 600 |
| `opacity` | 100 | 0 | 100 |
| `floating_panel_width` | 360 | 200 | 800 |
| `floating_panel_max_items` | 12 | 1 | 50 |
| `floating_panel_danmu_per_second` | 1 | 1 | 5 |
| `floating_panel_lifetime_sec` | 7 | 2 | 60 |
| `floating_panel_x_offset` | 20 | 0 | 400 |
| `floating_panel_y_offset` | 80 | 0 | 400 |
| `floating_panel_opacity` | 85 | 0 | 100 |
| `font_size` | 24 | 12 | 72 |
| `floating_panel_font_size` | 20 | 12 | 48 |

布尔值输出 `"0"` 或 `"1"`。`mic_use_visual_model` 保留历史的大小写敏感转换；其他简单布尔值按已有规范去空格并转换小写。浮点字段保留既有默认、界限与三位小数序列化，未扩大 NaN/Infinity 容错。

跨字段与领域规则仍显式执行：模型 endpoint/API family、麦克风模式、弹幕密度/批次、render/layout choice、屏幕坐标、字体及受管 CSS 文件名。风格 preset 在字段规范化后扩展，不能随意改变顺序；完整载荷与局部载荷都应通过现有 config-service、roundtrip、跨域事务和 Web payload 测试。
