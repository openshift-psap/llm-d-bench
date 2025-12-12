#!/usr/bin/env bash
# Run multiple experiments in a pipeline-like manner
set -euo pipefail

CHART_PATH="./llm-d-bench"
NAMESPACE="downstream-llm-d"
EXPERIMENT_DIR="llm-d-bench/experiments"

wait_for_job() {
    local job_name=$1
    echo "⏳ Waiting for job '$job_name' to complete..."
    
    oc wait --for=condition=complete \
        --timeout=7200s \
        job/"$job_name" \
        -n "$NAMESPACE" || {
        echo "❌ Job failed or timed out"
        oc logs -n "$NAMESPACE" -l "job=$job_name" --tail=50
        return 1
    }
    
    echo "✅ Job '$job_name' completed"
}

get_job_name() {
    grep -E "^\s*name:" "$1" | head -1 | awk '{print $2}' | tr -d '"'
}

uninstall_matching_releases() {
    local pattern=$1
    
    local releases
    releases=$(helm list -n "$NAMESPACE" -q 2>/dev/null || true)
    
    if [ -z "$releases" ]; then
        return 0
    fi
    
    local matching_releases=()
    while IFS= read -r release; do
        case "$release" in
            $pattern)
                matching_releases+=("$release")
                ;;
        esac
    done <<EOF
$releases
EOF
    
    if [ ${#matching_releases[@]} -eq 0 ]; then
        echo "ℹ️  No releases match pattern: $pattern"
        return 0
    fi
    
    echo "🗑️  Found ${#matching_releases[@]} matching release(s) to uninstall"
    for release in "${matching_releases[@]}"; do
        echo "    Uninstalling: $release"
        helm uninstall "$release" -n "$NAMESPACE" >/dev/null
    done
    
    echo "⏳ Waiting for cleanup..."
    sleep 5
}

main() {
    local pattern=${1:-}
    
    if [ -z "$pattern" ]; then
        echo "Usage: $0 <pattern>"
        echo "Example: $0 'meta-llama-3.1-8b-*'"
        echo "Example: $0 '*1k-1k*'"
        exit 1
    fi
    
    local experiments=()
    local find_output
    find_output=$(find "$EXPERIMENT_DIR" -maxdepth 1 -name "$pattern" -type f | sort)
    
    while IFS= read -r file; do
        [ -n "$file" ] && experiments+=("$file")
    done <<EOF
$find_output
EOF

    if [ ${#experiments[@]} -eq 0 ]; then
        echo "❌ No experiments found: $pattern"
        exit 1
    fi
    
    echo "📋 Found ${#experiments[@]} experiment(s) matching pattern: $pattern"
    echo ""
    echo "Experiments to run:"
    for i in "${!experiments[@]}"; do
        local exp_file="${experiments[$i]}"
        local exp_name=$(basename "$exp_file")
        echo "  $((i+1)). $exp_name"
    done
    
    echo ""
    echo "Enter experiment numbers to run (comma-separated, e.g., '1,3,5')"
    echo "Press Enter to run all, or type 'q' to quit:"
    read -p "> " selection
    
    if [[ "$selection" == "q" ]]; then
        echo "❌ Aborted by user"
        exit 0
    fi
    
    local selected_experiments=()
    
    if [ -z "$selection" ]; then
        selected_experiments=("${experiments[@]}")
        echo "✓ Running all experiments"
    else
        IFS=',' read -ra indices <<< "$selection"
        for idx in "${indices[@]}"; do
            idx=$(echo "$idx" | xargs)
            
            if ! [[ "$idx" =~ ^[0-9]+$ ]]; then
                echo "❌ Invalid input: '$idx' is not a number"
                exit 1
            fi
            
            local array_idx=$((idx - 1))
            if [ "$array_idx" -lt 0 ] || [ "$array_idx" -ge ${#experiments[@]} ]; then
                echo "❌ Invalid experiment number: $idx (valid range: 1-${#experiments[@]})"
                exit 1
            fi
            
            selected_experiments+=("${experiments[$array_idx]}")
        done
        
        echo "✓ Selected ${#selected_experiments[@]} experiment(s):"
        for exp in "${selected_experiments[@]}"; do
            echo "    - $(basename "$exp")"
        done
    fi
    
    echo ""
    echo "▶️  Starting experiment pipeline..."
    
    for exp_file in "${selected_experiments[@]}"; do
        local exp_name=$(basename "$exp_file" .yaml)
        exp_name=$(echo "$exp_name" | tr '[:upper:]' '[:lower:]' | tr -c 'a-z0-9.-' '-' | cut -c1-52 | sed 's/-$//')
        local job_name=$(get_job_name "$exp_file")
        
        echo ""
        echo "🧹 Cleaning up before running: $exp_name"
        uninstall_matching_releases "$pattern"
        
        echo ""
        echo "🚀 Running: $exp_name"
        
        helm upgrade --install "$exp_name" "$CHART_PATH" -f "$exp_file" -n "$NAMESPACE" >/dev/null
        
        sleep 5
        wait_for_job "$job_name" || exit 1
    done
    
    echo ""
    echo "🧹 Final cleanup after all experiments"
    uninstall_matching_releases "$pattern"
    
    echo ""
    echo "🎉 All experiments completed!"
}

main "$@"
