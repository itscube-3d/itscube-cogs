import os

BASE_POOL_100 = [
    "Cube","Sphere","Plane","Cylinder","Cone","Torus","Icosphere","Capsule","Pyramid","Suzanne",
    "Tetrahedron","Octahedron","Dodecahedron","Icosahedron","Prism","Tri-Prism","Hex Prism","Arch","Stair","Gear",
    "Offset Gear","Bevel Gear","Helix","Coil","Spring","Knot","Trefoil","Mobius","Lattice","Dome",
    "Vault","Arc","Bridge","Truss","Beam","Bracket","Frame","Panel","Louver","Grille",
    "Vent","Fan","Rotor","Propeller","Blade","Wing","Fin","Rudder","Rail","Track",
    "Ramp","Spiral Stair","Spline Arc","Bezier Orb","NURBS Surface","Patch","Voronoi Shell","Boolean Core","Arrayed Fan","Catmull Dome",
    "Subdivision Relic","Lattice Heart","Low-Poly Arch","Pillar","Column","Obelisk","Monolith","Slab","Tile","Brick",
    "Wedge","Chisel","Keystone","Ring","Halo","Torus Knot","Donut","Bowl","Vase","Amphora",
    "Bottle","Flask","Test Tube","Tube","Pipe","Elbow","Tee Junction","Manifold","Nozzle","Jet",
    "Lens","Prism Lens","Mirror","Reflector","Antenna","Dish","Radar","Satellite","Pod","Module"
]

TEMPLATE = "white background, black outline {mesh} icon, flat vector pictogram, uniform stroke, centered, no shading --ar 1:1 --stylize 50 --sref https://cdn.discordapp.com/attachments/1392533420860506285/1455889164099649770/reference-icon.png?ex=69565df1&is=69550c71&hm=c59418ca7a58213e62508fbef1fc79b9db4d5695b9b94a3efec628aa4358c3ba&"

def main():
    output_path = os.path.join(os.path.dirname(__file__), "prompts.txt")
    
    with open(output_path, "w") as f:
        for mesh in BASE_POOL_100:
            prompt = TEMPLATE.format(mesh=mesh.upper()) # Using uppercase for mesh name as in the example CHISEL
            f.write(prompt + "\n")
            
    print(f"Generated {len(BASE_POOL_100)} prompts to {output_path}")

if __name__ == "__main__":
    main()
