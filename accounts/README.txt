One JSON file per account. Tokens are stored in PLAIN TEXT - keep this folder private and do not sync it.

多用户部署：AAC OAuth 配置使用 AAC_BASE_URL、AAC_CLIENT_ID、AAC_REDIRECT_URI；租户数据根目录使用 WB_DATA_ROOT。旧账号必须通过 scripts/migrate-legacy-tenant.py 显式绑定 owner-user-id，dry-run 只输出文件数量和脱敏 ID。
