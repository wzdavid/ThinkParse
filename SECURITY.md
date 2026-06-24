# Security Policy

## Supported Versions

We actively support security updates for the following versions:

| Version | Supported          |
| ------- | ------------------ |
| 1.0.x   | :white_check_mark: |
| < 1.0   | :x:                |

## Reporting a Vulnerability

We take the security of ThinkParse seriously. If you believe you have found a security vulnerability, please report it to us as described below.

### How to Report

**Please do not report security vulnerabilities through public GitHub issues.**

Instead, please report them via one of the following methods:

1. **Email**: Send an email to [wzdavid@gmail.com](mailto:wzdavid@gmail.com) with details about the vulnerability
2. **GitHub Security Advisory**: Use GitHub's [Private Vulnerability Reporting](https://github.com/wzdavid/ThinkParse/security/advisories/new) feature

### What to Include

When reporting a vulnerability, please include:

- Type of vulnerability (e.g., XSS, SQL injection, authentication bypass)
- Full paths of source file(s) related to the vulnerability
- The location of the affected code (tag/branch/commit or direct URL)
- Step-by-step instructions to reproduce the issue
- Proof-of-concept or exploit code (if possible)
- Impact of the vulnerability

### What to Expect

- **Acknowledgment**: We will acknowledge receipt of your report within 48 hours
- **Initial Assessment**: We will provide an initial assessment within 7 days
- **Updates**: We will keep you informed of our progress every 7-10 days
- **Resolution**: We will work to resolve the issue as quickly as possible

### Disclosure Policy

- We will coordinate with you on the disclosure timeline
- We will credit you in the security advisory (unless you prefer to remain anonymous)
- We will not disclose the vulnerability publicly until a fix is available

## Security Best Practices

### For Users

1. **Keep Dependencies Updated**
   - Regularly update all dependencies to the latest secure versions
   - Use `pip list --outdated` to check for outdated packages
   - Enable Dependabot alerts on GitHub

2. **Environment Variables**
   - Never commit `.env` files to version control
   - Use strong, unique passwords for Redis, S3, and MinIO
   - Rotate credentials regularly
   - Use secrets management tools in production (e.g., HashiCorp Vault, AWS Secrets Manager)

3. **Network Security**
   - Run services behind a reverse proxy (Nginx, Traefik)
   - Use HTTPS/TLS for all external communications
   - Restrict Redis access to internal networks only
   - Implement rate limiting on API endpoints

4. **Container Security**
   - Use official base images
   - Regularly update base images
   - Run containers with non-root users when possible
   - Scan images for vulnerabilities (e.g., Trivy, Snyk)

5. **File Upload Security**
   - Validate file types and sizes
   - Scan uploaded files for malware
   - Store uploaded files in isolated locations
   - Implement file size limits

### For Developers

1. **Code Review**
   - All code changes must be reviewed before merging
   - Pay special attention to:
     - User input validation
     - File operations
     - Network requests
     - Authentication/authorization logic

2. **Dependency Management**
   - Regularly audit dependencies for vulnerabilities
   - Use `pip-audit` or `safety` to check for known vulnerabilities
   - Pin dependency versions in production

3. **Secrets Management**
   - Never hardcode secrets in source code
   - Use environment variables or secrets management tools
   - Rotate secrets regularly
   - Use different credentials for development and production

4. **Input Validation**
   - Validate and sanitize all user inputs
   - Use parameterized queries (if applicable)
   - Implement file type and size validation
   - Be cautious with file paths (prevent path traversal)

5. **Error Handling**
   - Don't expose sensitive information in error messages
   - Log errors securely without exposing secrets
   - Use appropriate HTTP status codes

## Known Security Considerations

### Current Limitations

1. **CORS Configuration**: Default CORS allows all origins (`allow_origins=["*"]`). In production, restrict to specific domains.

2. **Redis Security**: By default, Redis may not require authentication. Ensure Redis is:
   - Only accessible from internal networks
   - Protected with a strong password
   - Using TLS in production

3. **File Storage**: Temporary files may contain sensitive information. Ensure:
   - Proper cleanup of temporary files
   - Secure file permissions
   - Encryption at rest for sensitive data

## Security Updates

Security updates will be released as:
- **Patch versions** (e.g., 1.0.1) for critical security fixes
- **Minor versions** (e.g., 1.1.0) for security improvements

All security updates will be documented in:
- [CHANGELOG.md](CHANGELOG.md)
- GitHub Security Advisories
- Release notes

## Security Checklist for Deployment

Before deploying to production, ensure:

- [ ] All dependencies are up to date
- [ ] Strong passwords/credentials are set
- [ ] Redis is secured and not publicly accessible
- [ ] HTTPS/TLS is enabled
- [ ] CORS is configured for specific domains
- [ ] Rate limiting is implemented
- [ ] File upload limits are set
- [ ] Logging is configured (without exposing secrets)
- [ ] Monitoring and alerting are set up
- [ ] Backup and recovery procedures are in place
- [ ] Security scanning is enabled (e.g., Trivy, Snyk)

## Contact

For security-related questions or concerns, please contact:
- **Security Email**: [wzdavid@gmail.com](mailto:wzdavid@gmail.com)
- **GitHub Security**: [Use Private Vulnerability Reporting](https://github.com/wzdavid/ThinkParse/security/advisories/new)

Thank you for helping keep ThinkParse and its users safe!
