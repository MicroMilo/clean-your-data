# Action Playbook

Use this reference after the scanner has produced evidence. It translates classifications into cautious next actions without treating size as permission to delete.

## Decision Matrix

| Finding | Likely owner | Default action | Do not do |
| --- | --- | --- | --- |
| Desktop or Downloads accumulation | User workflow | Promote durable items, then archive the inbox by age | Bulk-delete by size alone |
| Codex or other AI workspace | Agent/tool workflow | Review outputs, promote durable deliverables, archive scratch work | Delete a whole date or session tree blindly |
| Git repository with dirty entries | User/project | Commit, stash, export, or inspect before moving | Move or remove without preserving changes |
| Feishu/Lark, WeChat, Slack, Teams, or similar app state | Owning app | Use the app's storage, cache, or export controls | Delete the container directly |
| Cloud-sync directory | Sync provider and user | Check sync status, retention, and online-only options | Delete a synced root to reclaim local space |
| `node_modules`, `.venv`, `build`, `dist`, `.next`, `target` | Project toolchain | Confirm rebuild command and remove only after approval | Assume every directory is disposable |
| Unknown path | Unknown | Inspect shallow metadata or ask the user | Invent a classification |

## Report Questions

For every significant finding, answer:

1. What is it?
2. What created it?
3. Who owns the lifecycle?
4. Is it durable, temporary, synchronized, or rebuildable?
5. What is the least risky useful action?
6. What would the user lose, and how could it be recovered?

## Recommendation Vocabulary

- **Promote** means copy or move a selected durable output into a stable, intentional location after review.
- **Archive** means retain the data in a dated or project-scoped location that is no longer part of the active workspace.
- **Use the owning app** means point the user to the app's own storage, export, cache, or retention controls.
- **Rebuildable candidate** means the data may be regenerated, but the report must name the rebuild hint and retain an approval gate.
- **Review** means the scanner lacks enough evidence to make a safe recommendation.

## Suggested Stable Roots

Use an existing project convention when one is present. Otherwise suggest a structure such as:

```text
~/work/
~/research/
~/papers/
~/personal/
~/src/<host>/<owner>/<repo>/
~/archive/YYYY-MM/
```

Do not propose migration of dirty repositories until their status has been checked.
