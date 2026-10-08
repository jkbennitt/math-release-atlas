# Select at most one open sync pull request owned by the Actions app on this repository.
# A fork, a human author, or any other head name is ignored. Two matches are an error.
[
  .[]
  | select(
      .isCrossRepository == false
      and (.author.is_bot == true)
      and (
        .author.login == "github-actions[bot]"
        or .author.login == "app/github-actions"
      )
      and (.headRefName | type == "string" and test("^upstream-sync(-[0-9a-f]{12})?$"))
    )
  | {number, headRefName}
]
| if length > 1 then error("more than one sync pull request") else . end
