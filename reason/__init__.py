from .reason import Reason

__red_end_user_data_statement__ = "This cog stores user IDs for the purpose of opting out of random mentions."

async def setup(bot):
    await bot.add_cog(Reason(bot))
