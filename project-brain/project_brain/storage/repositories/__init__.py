"""
project_brain/storage/repositories/ — SQL 操作層

每個 Repository 只做 SQL 操作，不含業務邏輯。
所有 Repository 透過 WriteContext 存取資料庫。
"""
