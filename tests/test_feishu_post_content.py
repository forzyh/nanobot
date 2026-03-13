# =============================================================================
# 飞书 POST 内容测试
# 文件路径：tests/test_feishu_post_content.py
#
# 这个文件的作用是什么？
# -------------------------
# 这个文件实现了飞书 (Feishu) 渠道的 POST 内容提取测试，主要测试：
# 1. _extract_post_content 函数解析飞书 POST 消息格式
# 2. _register_optional_event 辅助方法的容错处理
#
# 测试场景：
# --------
# 1. test_extract_post_content_supports_post_wrapper_shape
#    - 测试解析带 "post" 包装器的飞书消息格式
#    - 验证 zh_cn 语言的内容提取
#    - 验证文本和图片的提取
#
# 2. test_extract_post_content_keeps_direct_shape_behavior
#    - 测试解析直接格式（无 "post" 包装器）
#    - 验证向后兼容性
#
# 3. test_register_optional_event_keeps_builder_when_method_missing
#    - 测试当方法不存在时保持 Builder 不变
#
# 4. test_register_optional_event_calls_supported_method
#    - 测试当方法存在时正确调用
#
# 飞书 POST 消息格式说明:
# -----------------
# 飞书富文本消息支持两种格式：
# 1. 包装器格式：{"post": {"zh_cn": {"title": "...", "content": [...]}}}
# 2. 直接格式：{"title": "...", "content": [...]}
#
# 使用示例：
# --------
# pytest tests/test_feishu_post_content.py -v
# =============================================================================

from nanobot.channels.feishu import FeishuChannel, _extract_post_content


def test_extract_post_content_supports_post_wrapper_shape() -> None:
    """测试 _extract_post_content 支持带包装器的飞书 POST 格式。

    验证场景：
    1. 飞书富文本消息使用 "post" 包装器
    2. 内容在 "zh_cn" 语言键下
    3. 提取标题和文本内容
    4. 提取图片的 image_key

    飞书 POST 消息结构:
    {
        "post": {
            "zh_cn": {           # 语言代码
                "title": "日报",  # 消息标题
                "content": [     # 内容数组（二维数组）
                    [           # 每一行是一个元素数组
                        {"tag": "text", "text": "完成"},
                        {"tag": "img", "image_key": "img_1"},
                    ]
                ]
            }
        }
    }

    返回值:
    - text: 拼接后的文本（标题 + 所有文本内容）
    - image_keys: 所有图片的 image_key 列表
    """
    payload = {
        "post": {
            "zh_cn": {
                "title": "日报",
                "content": [
                    [
                        {"tag": "text", "text": "完成"},
                        {"tag": "img", "image_key": "img_1"},
                    ]
                ],
            }
        }
    }

    text, image_keys = _extract_post_content(payload)

    # 验证文本提取：标题 + 文本内容
    assert text == "日报 完成"
    # 验证图片提取
    assert image_keys == ["img_1"]


def test_extract_post_content_keeps_direct_shape_behavior() -> None:
    """测试 _extract_post_content 保持直接格式的向后兼容性。

    验证场景：
    1. 消息没有 "post" 包装器，直接是内容
    2. 函数应该正确解析这种格式
    3. 确保与旧版本代码兼容

    直接格式结构:
    {
        "title": "Daily",
        "content": [
            [
                {"tag": "text", "text": "report"},
                {"tag": "img", "image_key": "img_a"},
                {"tag": "img", "image_key": "img_b"},
            ]
        ]
    }

    设计说明:
    - 支持两种格式确保向后兼容
    - 函数自动检测格式类型
    """
    payload = {
        "title": "Daily",
        "content": [
            [
                {"tag": "text", "text": "report"},
                {"tag": "img", "image_key": "img_a"},
                {"tag": "img", "image_key": "img_b"},
            ]
        ],
    }

    text, image_keys = _extract_post_content(payload)

    # 验证文本提取
    assert text == "Daily report"
    # 验证多个图片的提取
    assert image_keys == ["img_a", "img_b"]


def test_register_optional_event_keeps_builder_when_method_missing() -> None:
    """测试 _register_optional_event 在方法缺失时保持 Builder 不变。

    验证场景：
    1. Builder 对象没有 register_event 方法
    2. 函数应该静默跳过，不抛出异常
    3. 返回原始 Builder 对象

    设计说明:
    - 这是容错处理，允许不同版本的 Builder
    - 如果方法不存在，不做任何操作
    - 这种模式称为"可选接口"或"鸭子类型"
    """
    class Builder:
        pass  # 没有任何方法

    builder = Builder()
    # 调用不存在的方法，应该静默跳过
    same = FeishuChannel._register_optional_event(builder, "missing", object())
    assert same is builder  # 返回原始对象


def test_register_optional_event_calls_supported_method() -> None:
    """测试 _register_optional_event 在方法存在时正确调用。

    验证场景：
    1. Builder 对象有 register_event 方法
    2. 函数应该调用该方法并传入 handler
    3. 返回原始 Builder 对象（支持链式调用）

    设计说明:
    - 使用 hasattr 检查方法是否存在
    - 调用方法时传入 handler 参数
    - 返回 builder 支持链式调用风格
    """
    called = []

    class Builder:
        def register_event(self, handler):
            """模拟 register_event 方法。

            Args:
                handler: 事件处理器对象
            """
            called.append(handler)
            return self  # 支持链式调用

    builder = Builder()
    handler = object()
    same = FeishuChannel._register_optional_event(builder, "register_event", handler)

    # 验证返回原始对象
    assert same is builder
    # 验证方法被调用且传入了正确的 handler
    assert called == [handler]
