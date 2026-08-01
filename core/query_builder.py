from dataclasses import dataclass
from typing import List


@dataclass
class RetrievalQuery:
    text: str
    category: str
    weight: float = 1.0


class QueryBuilder:
    @staticmethod
    def build(state) -> List[RetrievalQuery]:
        queries = []

        # High weight: Changed files
        for f in state.get("pr_analysis", {}).get("changed_files", []):
            queries.append(RetrievalQuery(text=f, category="file", weight=1.0))

        # High weight: Functions
        for f in state.get("pr_analysis", {}).get("added_functions", []):
            queries.append(RetrievalQuery(text=f, category="symbol", weight=0.9))

        for f in state.get("pr_analysis", {}).get("modified_functions", []):
            queries.append(RetrievalQuery(text=f, category="symbol", weight=0.8))

        # Medium weight: Natural language
        queries.append(RetrievalQuery(
            text=f"{state.get('title', '')}\n{state.get('body', '')}",
            category="natural_language",
            weight=0.7
        ))

        # Medium weight: Affected areas
        for area in state.get("pr_understanding", {}).get("affected_areas", []):
            queries.append(RetrievalQuery(text=area, category="domain", weight=0.6))

        # Low weight: Keywords from PR title and body (dynamic)
        title_body = f"{state.get('title', '')} {state.get('body', '')}"
        keywords = [word for word in title_body.split() if len(word) > 3]
        if keywords:
            queries.append(RetrievalQuery(
                text=" ".join(keywords[:10]),
                category="keyword",
                weight=0.4
            ))

        return queries