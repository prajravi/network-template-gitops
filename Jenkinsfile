/*
 * Jenkinsfile for Network Template GitOps
 *
 * Runs on a local Jenkins instance with Docker support.
 * Pipeline stages:
 *   1. Build Docker image
 *   2. Validate Stage  -- ensure templates exist in Stage project
 *   3. Drift Check     -- Git content == Stage content
 *   4. Approval Gate   -- manual approval by a senior engineer
 *   5. Re-validate Drift -- ensure nothing changed after approval
 *   6. Promote         -- import templates from Stage into Prod project
 */

pipeline {
    agent any

    environment {
        IMAGE_NAME = "network-template-gitops"
    }

    stages {

        stage('Docker Build') {
            steps {
                script {
                    echo "--- Building Docker image: ${IMAGE_NAME}:latest ---"
                    sh "docker build -t ${IMAGE_NAME}:latest ."
                    echo "Build completed."
                }
            }
        }

        stage('Validate Stage') {
            steps {
                script {
                    echo "--- Validating templates exist in Stage project ---"
                    sh """
                    docker run --rm \
                        --env-file .env \
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
                    docker run --rm \
                        --env-file .env \
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
                    docker run --rm \
                        --env-file .env \
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
                    docker run --rm \
                        --env-file .env \
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
            sh "docker images ${IMAGE_NAME} -q | xargs docker rmi -f || true"
        }
        failure {
            echo "Pipeline failed. Check the logs above for details."
        }
        success {
            echo "Pipeline completed successfully."
        }
    }
}
