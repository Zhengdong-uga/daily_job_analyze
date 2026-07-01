import os
from pathlib import Path
from typing import Dict, Any, List

import matplotlib.pyplot as plt
import seaborn as sns

def generate_skill_demand_chart(skill_counts: Dict[str, int], output_path: str | Path) -> str:
    """
    Generate a sleek, minimal horizontal bar chart for top skills.
    
    Args:
        skill_counts: A dictionary mapping skill names to their mention count.
        output_path: Where to save the generated chart.
        
    Returns:
        The string path to the saved chart image.
    """
    # Convert dict to list of tuples
    all_skills = list(skill_counts.items())
            
    # Sort and get top 10
    all_skills.sort(key=lambda x: x[1], reverse=True)
    top_skills = all_skills[:10]
    
    if not top_skills:
        return ""
        
    # Reverse to have the highest at the top in a horizontal bar chart
    top_skills.reverse()
    
    skills = [s[0] for s in top_skills]
    counts = [s[1] for s in top_skills]
    
    # Set sleek aesthetic (Morning Brew style: clean, no borders, modern)
    sns.set_theme(style="whitegrid", rc={"axes.facecolor": "#ffffff", "figure.facecolor": "#ffffff"})
    plt.figure(figsize=(10, 5))
    
    # Create horizontal barplot
    ax = sns.barplot(
        x=counts, 
        y=skills, 
        color="#4f46e5",  # Premium Indigo
        edgecolor="none"
    )
    
    # Move y-axis labels to the right to left-align the bars
    ax.yaxis.tick_right()
    
    # Remove top, right, and left spines
    sns.despine(left=True, right=True, bottom=False)
    
    # Customize grid and axes
    ax.grid(axis='x', linestyle='--', alpha=0.7, color='#e5e7eb')
    ax.grid(axis='y', visible=False)
    
    # Customize labels
    ax.set_xlabel('Number of Mentions', fontsize=10, color='#4b5563', weight='normal', labelpad=10)
    ax.set_ylabel('')
    
    # Style tick labels
    plt.xticks(fontsize=9, color='#6b7280')
    # Set tick parameters: align labels left against the right axis
    ax.tick_params(axis='y', labelsize=10, labelcolor='#1f2937', pad=10)
    for label in ax.get_yticklabels():
        label.set_weight('normal')
        label.set_horizontalalignment('left')
        
    # Add Title
    plt.title('Top 10 Most In-Demand Skills Today', fontsize=14, color='#111827', weight='bold', pad=15, loc='left')
    
    # Add count labels at the end of each bar
    for i, p in enumerate(ax.patches):
        width = p.get_width()
        ax.text(width + max(counts)*0.01,
                p.get_y() + p.get_height()/2. + 0.1,
                f'{int(width)}',
                ha="left",
                fontsize=10,
                color='#4b5563',
                weight='normal')
                
    # Ensure layout fits well
    try:
        plt.tight_layout()
    except Exception:
        pass
    
    # Save chart
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    plt.savefig(output_path, dpi=200, bbox_inches='tight')
    plt.close()
    
    return str(output_path)
