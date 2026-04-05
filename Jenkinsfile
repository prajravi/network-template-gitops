/*
 * Jenkinsfile for Network Template GitOps
 *
 * Runs on a local Jenkins instance (macOS) with Docker.
 * Each pipeline stage runs inside a container for isolation and
 * reproducibility -- the same image can be deployed to any CI system.
 *
 * Pipeline stages:
 *   1. Docker Build       -- build the application image
 *   2. Validate Stage     -- ensure templates exist in Stage project
 *   3. Drift Check        -- Git content == Stage content
 *   4. Approval Gate      -- manual approval by a senior engineer
 *   5. Re-validate Drift  -- ensure nothing changed after approval
 *   6. Promote            -- import templates from Stage into Prod project
 */

pipeline {
    agent any

    environment {
        IMAGE_NAME  = "network-template-gitops"
        DOCKER_BIN  = "/usr/local/bin/docker"
        ENV_FILE    = "${WORKSPACE}/.env"
        PATH        = "/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
    }

    stages {

        stage('Docker Build') {
            steps {
                script {
                    sh """
                    if [ ! -f ${ENV_FILE} ]; then
                        echo "ERROR: .env file not found at ${ENV_FILE}"
                        echo "Copy your .env into the Jenkins workspace first."
                        exit 1
                    fi
                    """
                    echo "--- Building Docker image: ${IMAGE_NAME}:latest ---"
                    sh "${DOCKER_BIN} build -t ${IMAGE_NAME}:latest ."
                    echo "Build completed."
                }
            }
        }

        stage('Validate Stage') {
            steps {
                script {
                    echo "--- Validating templates exist in Stage project ---"
                    sh """
                    ${DOCKER_BIN} run --rm \
                        --env-file ${ENV_FILE} \
                        ${IMAGE_NAME}:latest \
                        --commit ${env.GIT_COMMIT} \
                        --branch ${env.BRANCH_NAME} \
                        --stage validate-stage
                    """
                    echo "Stage validation passed."
                }
            }
        }

        stage('Drift Check') {
            steps {
                script {
                    echo "--- Checking for drift: Git vs Stage ---"
                    sh """
                    ${DOCKER_BIN} run --rm \
                        --env-file ${ENV_FILE} \
                        ${IMAGE_NAME}:latest \
                        --commit ${env.GIT_COMMIT} \
                        --branch ${env.BRANCH_NAME} \
                        --stage drift-check
                    """
                    echo "Drift check passed."
                }
            }
        }

        stage('Approval Gate') {
            when {
                branch 'main'
            }
            steps {
                input message: 'Approve promotion to Prod?', submitter: ''
            }
        }

        stage('Re-validate Drift') {
            when {
                branch 'main'
            }
            steps {
                script {
                    echo "--- Re-validating drift after approval ---"
                    sh """
                    ${DOCKER_BIN} run --rm \
                        --env-file ${ENV_FILE} \
                        ${IMAGE_NAME}:latest \
                        --commit ${env.GIT_COMMIT} \
                        --branch ${env.BRANCH_NAME} \
                        --stage drift-check
                    """
                    echo "Post-approval drift check passed."
                }
            }
        }

        stage('Promote to Prod') {
            when {
                branch 'main'
            }
            steps {
                script {
                    echo "--- Promoting templates from Stage to Prod ---"
                    sh """
                    ${DOCKER_BIN} run --rm \
                        --env-file ${ENV_FILE} \
                        ${IMAGE_NAME}:latest \
                        --commit ${env.GIT_COMMIT} \
                        --branch ${env.BRANCH_NAME} \
                        --stage promote
                    """
                    echo "Promotion completed."
                }
            }
        }
    }

    post {
        always {
            sh "${DOCKER_BIN} rmi ${IMAGE_NAME}:latest || true"
        }
        failure {
            echo "Pipeline failed. Check the logs above for details."
        }
        success {
            echo "Pipeline completed successfully."
        }
    }
}
