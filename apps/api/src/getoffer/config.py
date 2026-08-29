"""配置：显式声明，启动即校验。除本地基础设施端口外不提供隐式兜底（spec §7）。

.env 与 data 目录锚定到 apps/api 自身路径，不依赖进程 cwd（后台任务从任意目录启动均可）。
"""

from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel
from pydantic_settings import BaseSettings, SettingsConfigDict

API_ROOT = Path(__file__).resolve().parents[2]  # apps/api
DATA_ROOT = API_ROOT.parent.parent / "data"  # 仓库根 data（与 agents、docker 卷同源）


class LLMProviderConfig(BaseModel):
    """单个 LLM 供应商的显式配置。

    网关不做供应商间降级（spec §7）：换模型是部署决策，不是运行时兜底。
    """

    name: str = "deepseek"
    base_url: str = "https://api.deepseek.com/v1"
    model: str = "deepseek-v4-flash-vision-exp"
    api_key: str = ""  # 为空时 LLM 调用抛 NotConfigured，其他功能不受影响
    # 思考型模型的推理开关（DeepSeek: thinking={"type":"disabled"}）。
    # 结构化抽取/评分等机械任务默认关闭：更快更省，也避免推理挤占输出预算。
    disable_thinking: bool = True


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="GETOFFER_",
        env_nested_delimiter="__",
        env_file=str(API_ROOT / ".env"),
        extra="ignore",
    )

    database_url: str = "postgresql+asyncpg://getoffer:getoffer@localhost:24432/getoffer"
    meilisearch_url: str = "http://127.0.0.1:27700"
    meilisearch_key: str = ""
    redis_url: str = "redis://localhost:26379/0"
    # git 克隆代理（如 http://127.0.0.1:7897）；空 = 直连
    git_proxy: str = ""
    data_dir: Path = DATA_ROOT

    # 开发期便利（建表交给 SQLAlchemy）；正式迁移走 alembic，见 README
    auto_create_tables: bool = True

    llm: LLMProviderConfig = LLMProviderConfig()

    @property
    def repos_dir(self) -> Path:
        return self.data_dir / "repos"

    @property
    def sessions_dir(self) -> Path:
        return self.data_dir / "sessions"

    def ensure_dirs(self) -> None:
        for directory in (self.data_dir, self.repos_dir, self.sessions_dir):
            directory.mkdir(parents=True, exist_ok=True)


@lru_cache(maxsize=1)
def load_settings() -> Settings:
    settings = Settings()
    settings.ensure_dirs()
    return settings
