from typing import List, Optional
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field
import pytz


class GoogleConfig(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="GOOGLE_")

    client_id: str = Field(..., description="Google OAuth client  ID")
    client_secret: str = Field(..., description="Google OAuth client secret")
    redirect_url: str = Field(default="http://localhost:8080/oauth/google/callback")
    access_token: Optional[str] = Field(default=None)
    refresh_token: Optional[str] = Field(default=None)

    scopes: List[str] = Field(default=[
        "https://www.googleapis.com/auth/calendar.readonly",
        "https://www.googleapis.com/auth/gmail.readonly",
    ])


class MicrosoftConfig(BaseSettings):
    """Microsoft Graph API configuration."""
    model_config = SettingsConfigDict(env_prefix="MICROSOFT_")

    client_id: str = Field(..., description="Azure App client ID")
    client_secret: str = Field(..., description="Azure App client secret")
    tenant_id: str = Field(default="common")
    redirect_uri: str = Field(default="http://localhost:8080/oauth/microsoft/callback")
    access_token: Optional[str] = Field(default=None)
    refresh_token: Optional[str] = Field(default=None)

    # Graph API scopes
    scopes: List[str] = Field(default=[
        "User.Read",
        "Mail.Read",
        "Calendars.Read",
        "offline_access",
    ])


class DiscordConfig(BaseSettings):
    """Discord bot configuration."""
    model_config = SettingsConfigDict(env_prefix="DISCORD_")

    bot_token: str = Field(..., description="Discord bot token")
    guild_id: int = Field(..., description="Server ID for slash commands")
    channel_id: int = Field(..., description="Channel for notifications")
    user_id: int = Field(..., description="Your user ID for security")


class SupabaseConfig(BaseSettings):
    """Supabase configuration."""
    model_config = SettingsConfigDict(env_prefix="SUPABASE_")

    url: str = Field(..., description="Supabase project URL")
    key: str = Field(..., description="Supabase anon key")
    service_key: Optional[str] = Field(default=None, description="Service role key")


class ProductivityDefaults(BaseSettings):
    """Default productivity settings (used until learning kicks in)."""
    model_config = SettingsConfigDict(env_prefix="")

    peak_productivity_hours: str = Field(default="9,10,11,15,16")
    avoid_hours: str = Field(default="13,14,22,23")
    preferred_block_length: int = Field(default=90, description="Minutes")
    break_between_blocks: int = Field(default=15, description="Minutes")
    max_daily_deep_work: int = Field(default=6, description="Hours")

    @property
    def peak_hours_list(self) -> List[int]:
        return [int(h) for h in self.peak_productivity_hours.split(",")]

    @property
    def avoid_hours_list(self) -> List[int]:
        return [int(h) for h in self.avoid_hours.split(",")]


class ScheduleConfig(BaseSettings):
    """Scheduling configuration."""
    model_config = SettingsConfigDict(env_prefix="")

    timezone: str = Field(default="America/New_York")
    morning_digest_hour: int = Field(default=8)
    morning_digest_minute: int = Field(default=0)
    weekly_plan_day: int = Field(default=6, description="0=Monday, 6=Sunday")
    weekly_plan_hour: int = Field(default=18)
    weekly_plan_minute: int = Field(default=0)
    sync_horizon_days: int = Field(default=30)
    deadline_warning_hours: str = Field(default="24,4,1")

    @property
    def tz(self) -> timezone:
        return pytz.timezone(self.timezone)

    @property
    def warning_hours_list(self) -> List[int]:
        return [int(h) for h in self.deadline_warning_hours.split(",")]


class Settings(BaseSettings):
    """Main settings class combining all configurations."""
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # API Keys
    openai_api_key: str = Field(..., description="OpenAI API key")

    # Paths
    syllabus_folder: str = Field(default="./syllabi")
    log_level: str = Field(default="INFO")

    # Sub-configurations
    google: GoogleConfig = Field(default_factory=GoogleConfig)
    microsoft: MicrosoftConfig = Field(default_factory=MicrosoftConfig)
    discord: DiscordConfig = Field(default_factory=DiscordConfig)
    supabase: SupabaseConfig = Field(default_factory=SupabaseConfig)
    productivity: ProductivityDefaults = Field(default_factory=ProductivityDefaults)
    schedule: ScheduleConfig = Field(default_factory=ScheduleConfig)

    @classmethod
    def load(cls) -> "Settings":
        """Load settings with nested configs."""
        return cls(
            google=GoogleConfig(),
            microsoft=MicrosoftConfig(),
            discord=DiscordConfig(),
            supabase=SupabaseConfig(),
            productivity=ProductivityDefaults(),
            schedule=ScheduleConfig(),
        )


# Global settings instance (lazy loaded)
_settings: Optional[Settings] = None


def get_settings() -> Settings:
    """Get or create settings instance."""
    global _settings
    if _settings is None:
        _settings = Settings.load()
    return _settings
