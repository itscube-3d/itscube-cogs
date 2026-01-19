from .model import Model

async def setup(bot):
    await bot.add_cog(Model(bot))
