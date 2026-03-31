# Contributing

感谢你愿意改进 `mineru-parser`。

## 开发环境

```bash
pip install -e ".[dev]"
```

## 提交流程

1. 创建分支
2. 完成开发与测试
3. 提交 PR（描述背景、改动点、验证方式）

## 代码规范

- 保持接口与配置向后兼容（尤其是 CLI 参数）
- 新增配置项时同步更新 `mineru_parser/default_config.yml`
- 修改文档输出逻辑时补充或更新测试

## 本地验证

```bash
pytest -q
```

## 安全要求

- 不要提交任何真实 API Token / 密钥
- 不要提交本地缓存与解析产物
- 如发现历史泄漏，请先轮换凭据再提 PR

