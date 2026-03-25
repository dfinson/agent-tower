# Page snapshot

```yaml
- generic [ref=e2]:
  - generic [ref=e3]:
    - banner [ref=e4]:
      - link "CodePlane" [ref=e5] [cursor=pointer]:
        - /url: /
        - generic [ref=e6]: CodePlane
      - generic [ref=e7]:
        - 'generic "Connection status: Connected" [ref=e8]': Connected
        - button "Open navigation menu" [ref=e10] [cursor=pointer]:
          - img [ref=e11]
    - main [ref=e12]:
      - generic [ref=e13]:
        - heading "Jobs" [level=3] [ref=e15]
        - generic [ref=e16]:
          - generic [ref=e17]:
            - img
            - textbox "Filter active jobs…" [ref=e18]
          - generic [ref=e19]:
            - button "In Progress" [ref=e20] [cursor=pointer]
            - button "Awaiting Input" [ref=e21] [cursor=pointer]
            - button "Failed" [ref=e22] [cursor=pointer]
          - generic [ref=e24]:
            - img [ref=e26]
            - generic [ref=e29]:
              - paragraph [ref=e30]: No jobs running
              - paragraph [ref=e31]: Create a new job to get started
            - button "New Job" [ref=e32] [cursor=pointer]:
              - img [ref=e33]
              - text: New Job
        - button "New Job" [ref=e34] [cursor=pointer]:
          - img [ref=e35]
  - region "Notifications alt+T"
```