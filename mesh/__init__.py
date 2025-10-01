from .mesh import Mesh

async def setup(bot):
    await bot.add_cog(Mesh(bot))
