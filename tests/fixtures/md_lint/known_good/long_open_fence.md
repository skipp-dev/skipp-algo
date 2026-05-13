# Long opening fence

CommonMark §4.5: a closing fence must use the same token AND be at
least as long as the opener. The 3-backtick run on the middle line below
is content, not a closer; the real closer is the 4-backtick line.

````text
inner ``` does not close this 4-backtick fence
some `lonely` token that would otherwise be flagged inline
````

Trailing prose with a balanced `inline span` to confirm the lint
returned to the non-fence parser correctly.
