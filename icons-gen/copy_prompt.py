import os
import subprocess
import sys

def copy_to_clipboard(text):
    process = subprocess.Popen('pbcopy', env={'LANG': 'en_US.UTF-8'}, stdin=subprocess.PIPE)
    process.communicate(text.encode('utf-8'))

def main():
    base_dir = os.path.dirname(__file__)
    prompts_file = os.path.join(base_dir, "prompts.txt")
    index_file = os.path.join(base_dir, ".prompt_index")

    if not os.path.exists(prompts_file):
        print(f"Error: {prompts_file} not found.")
        return

    # Read prompts
    with open(prompts_file, "r") as f:
        # Filter out empty lines just in case
        lines = [line.strip() for line in f if line.strip()]

    if not lines:
        print("Error: No prompts found.")
        return

    # Read current index
    current_index = 0
    if os.path.exists(index_file):
        try:
            with open(index_file, "r") as f:
                content = f.read().strip()
                if content:
                    current_index = int(content)
        except ValueError:
            current_index = 0

    # Check bounds
    if current_index >= len(lines):
        print(f"All {len(lines)} prompts have already been copied!")
        # Optional: Reset? 
        # current_index = 0
        return

    # Get prompt and copy
    prompt_to_copy = lines[current_index]
    copy_to_clipboard(prompt_to_copy)

    print(f"[{current_index + 1}/{len(lines)}] Copied to clipboard:")
    print(f"> {prompt_to_copy}")

    # Update index
    with open(index_file, "w") as f:
        f.write(str(current_index + 1))

if __name__ == "__main__":
    main()
