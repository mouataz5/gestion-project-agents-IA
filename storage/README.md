# storage/

Runtime data written by the application through the `StorageProvider` abstraction
(`backend/app/core/storage.py`). Everything here except this README and `.gitkeep` is git-ignored.

Planned layout (created on demand):

```
storage/
├── uploads/                       # user uploads (master CV versions)
├── applications/{application_id}/
│   ├── cv/                        # master_cv, tailored_cv.docx, tailored_cv.pdf, ats_report.json
│   ├── cover_letter/
│   └── screenshots/               # browser automation evidence
└── diagnostics/                   # transient files written by the system self-test
```

In Docker Compose this folder is bind-mounted into the backend and worker containers at `/app/storage`.
