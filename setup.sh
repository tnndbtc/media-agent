#!/bin/bash

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

# Function to print colored header
print_header() {
    echo -e "${CYAN}=====================================${NC}"
    echo -e "${CYAN}      media-agent - Setup Menu${NC}"
    echo -e "${CYAN}=====================================${NC}"
}

# Function to print menu options
print_menu() {
    echo -e "${BLUE}1)${NC} Run tests"
    echo -e "${BLUE}2)${NC} Install dependencies (requirements.txt)"
    echo -e "${BLUE}3)${NC} Show usage (generate_media.py)"
    echo -e "${BLUE}0)${NC} Exit"
    echo -e "${CYAN}=====================================${NC}"
}

# Function to run tests
run_tests() {
    echo -e "${YELLOW}Running tests...${NC}"

    # Resolve the directory containing this script so the command works
    # regardless of where setup.sh is invoked from.
    local script_dir
    script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

    # Prefer the project virtual environment if it exists; otherwise fall
    # back to whatever pytest is on PATH.
    local pytest_cmd
    if [[ -f "${script_dir}/.venv/bin/pytest" ]]; then
        pytest_cmd="${script_dir}/.venv/bin/pytest"
    elif [[ -f "${HOME}/.virtualenvs/ma/bin/pytest" ]]; then
        pytest_cmd="${HOME}/.virtualenvs/ma/bin/pytest"
    elif command -v pytest &>/dev/null; then
        pytest_cmd="pytest"
    else
        echo -e "${RED}Error: pytest not found. Install dependencies first (pip install -e '.[dev]').${NC}"
        return 1
    fi

    echo -e "${CYAN}$ (cd \"${script_dir}\" && \"${pytest_cmd}\" -q)${NC}"
    (cd "$script_dir" && "$pytest_cmd" -q)

    if [[ $? -eq 0 ]]; then
        echo -e "${GREEN}All tests passed!${NC}"
    else
        echo -e "${RED}Some tests failed.${NC}"
        return 1
    fi

    # --- Real workflow test: generate_media.py against e2e golden ---
    echo ""
    echo -e "${YELLOW}Running real workflow: generate_media.py...${NC}"

    local input="${script_dir}/third_party/contracts/goldens/e2e/example_episode/AssetManifest.json"
    local timestamp
    timestamp="$(date '+%Y-%m-%d_%H-%M-%S')"
    local output="/tmp/AssetManifest.media_${timestamp}.json"

    local python_cmd
    if [[ -f "${script_dir}/.venv/bin/python" ]]; then
        python_cmd="${script_dir}/.venv/bin/python"
    elif [[ -f "${HOME}/.virtualenvs/ma/bin/python" ]]; then
        python_cmd="${HOME}/.virtualenvs/ma/bin/python"
    elif command -v python3 &>/dev/null; then
        python_cmd="python3"
    else
        python_cmd="python"
    fi

    echo -e "${CYAN}$ \"${python_cmd}\" scripts/generate_media.py \\${NC}"
    echo -e "${CYAN}      --input  \"${input}\" \\${NC}"
    echo -e "${CYAN}      --output \"${output}\"${NC}"
    (cd "$script_dir" && "$python_cmd" scripts/generate_media.py \
        --input  "$input" \
        --output "$output")

    if [[ $? -ne 0 ]]; then
        echo -e "${RED}Workflow test failed.${NC}"
        return 1
    fi

    echo -e "${CYAN}$ ls -l \"${output}\"${NC}"
    ls -l "$output"

    local size
    size=$(stat -c%s "$output" 2>/dev/null || stat -f%z "$output" 2>/dev/null)
    if [[ -z "$size" || "$size" -eq 0 ]]; then
        echo -e "${RED}Error: output file is empty.${NC}"
        rm -f "$output"
        return 1
    fi

    echo -e "${GREEN}Workflow test passed! (${size} bytes)${NC}"
    echo -e "${CYAN}$ rm \"${output}\"${NC}"
    rm -f "$output"
    echo -e "${GREEN}Output cleaned up.${NC}"

    # --- Real workflow test: media resolve (orchestrator CLI form) ---
    echo ""
    echo -e "${YELLOW}Running real workflow: media resolve...${NC}"

    local output2="/tmp/AssetManifest.media_resolve_${timestamp}.json"

    echo -e "${CYAN}$ \"${python_cmd}\" scripts/media.py resolve \\${NC}"
    echo -e "${CYAN}      --in  \"${input}\" \\${NC}"
    echo -e "${CYAN}      --out \"${output2}\"${NC}"
    (cd "$script_dir" && "$python_cmd" scripts/media.py resolve \
        --in  "$input" \
        --out "$output2")

    if [[ $? -ne 0 ]]; then
        echo -e "${RED}media resolve test failed.${NC}"
        return 1
    fi

    echo -e "${CYAN}$ ls -l \"${output2}\"${NC}"
    ls -l "$output2"

    local size2
    size2=$(stat -c%s "$output2" 2>/dev/null || stat -f%z "$output2" 2>/dev/null)
    if [[ -z "$size2" || "$size2" -eq 0 ]]; then
        echo -e "${RED}Error: output file is empty.${NC}"
        rm -f "$output2"
        return 1
    fi

    echo -e "${GREEN}media resolve test passed! (${size2} bytes)${NC}"
    echo -e "${CYAN}$ rm \"${output2}\"${NC}"
    rm -f "$output2"
    echo -e "${GREEN}Output cleaned up.${NC}"
}

# Function to install Python dependencies from requirements.txt
install_requirements() {
    local script_dir
    script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

    local pip_cmd
    if [[ -f "${script_dir}/.venv/bin/pip" ]]; then
        pip_cmd="${script_dir}/.venv/bin/pip"
    elif [[ -f "${HOME}/.virtualenvs/ma/bin/pip" ]]; then
        pip_cmd="${HOME}/.virtualenvs/ma/bin/pip"
    elif command -v pip3 &>/dev/null; then
        pip_cmd="pip3"
    elif command -v pip &>/dev/null; then
        pip_cmd="pip"
    else
        echo -e "${RED}Error: pip not found. Please install Python/pip first.${NC}"
        return 1
    fi

    if [[ ! -f "${script_dir}/requirements.txt" ]]; then
        echo -e "${RED}Error: requirements.txt not found in ${script_dir}.${NC}"
        return 1
    fi

    echo -e "${YELLOW}Installing dependencies from requirements.txt...${NC}"
    "$pip_cmd" install -r "${script_dir}/requirements.txt"

    if [[ $? -eq 0 ]]; then
        echo -e "${GREEN}Dependencies installed successfully!${NC}"
    else
        echo -e "${RED}Failed to install dependencies.${NC}"
        return 1
    fi
}

# Function to show generate_media.py usage
show_generate_usage() {
    local script_dir
    script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

    echo -e "${GREEN}Resolve an AssetManifest into AssetManifest.media.json${NC}"
    echo ""
    echo -e "${CYAN}Preferred (orchestrator-compatible CLI):${NC}"
    echo -e "  media resolve \\"
    echo -e "      --in  /path/to/AssetManifest.json \\"
    echo -e "      --out /path/to/AssetManifest.media.json"
    echo ""
    echo -e "${CYAN}Fail if any asset is missing (no placeholders allowed):${NC}"
    echo -e "  media resolve \\"
    echo -e "      --in  /path/to/AssetManifest.json \\"
    echo -e "      --out /path/to/AssetManifest.media.json \\"
    echo -e "      --strict"
    echo ""
    echo -e "${CYAN}Direct script (same behaviour, long-form flags):${NC}"
    echo -e "  python ${script_dir}/scripts/generate_media.py \\"
    echo -e "      --input  /path/to/AssetManifest.json \\"
    echo -e "      --output /path/to/AssetManifest.media.json"
    echo ""
    echo -e "${CYAN}Short flags (direct script only):${NC}"
    echo -e "  python ${script_dir}/scripts/generate_media.py \\"
    echo -e "      -i /path/to/AssetManifest.json \\"
    echo -e "      -o /path/to/AssetManifest.media.json"
    echo ""
    echo -e "${CYAN}Via make:${NC}"
    echo -e "  make generate-media \\"
    echo -e "      INPUT=/path/to/AssetManifest.json \\"
    echo -e "      OUTPUT=/path/to/AssetManifest.media.json"
    echo ""
    echo -e "${CYAN}Environment variables (optional):${NC}"
    echo -e "  MEDIA_LIBRARY_ROOT   — path to local asset library"
    echo -e "  LOCAL_ASSETS_ROOT    — path to local assets directory"
    echo ""
    echo -e "${CYAN}Exit codes:${NC}"
    echo -e "  0  resolved successfully"
    echo -e "  1  resolver error or invalid input"
    echo -e "  2  bad arguments / input file not found"
}

# Main menu loop
main() {
    while true; do
        echo ""
        print_header
        print_menu

        read -p "Select an option [0-3]: " choice
        echo ""

        case $choice in
            1)
                run_tests
                ;;
            2)
                install_requirements
                ;;
            3)
                show_generate_usage
                ;;
            0)
                echo -e "${GREEN}Goodbye!${NC}"
                exit 0
                ;;
            *)
                echo -e "${RED}Invalid option. Please select 0-3.${NC}"
                ;;
        esac
    done
}

# Run main function
main
