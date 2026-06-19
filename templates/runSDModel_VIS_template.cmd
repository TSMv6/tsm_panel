rem @echo on

set PROJECT_DRIVE={PRJ_DRIVE}
set PROJECT_DIRECTORY={PRJ_DIR}
set SAMPLERATE=1
set ITERATION=1

%PROJECT_DRIVE%
cd %PROJECT_DRIVE%%PROJECT_DIRECTORY%
rem JVM memory allocations
set MEMORY_SPMARKET_MIN=30000m
set MEMORY_SPMARKET_MAX=150000m

rem set location of java
set JAVA_64_PATH={JDK_PATH}

set project.folder=%PROJECT_DIRECTORY%

rem ### First save the JAVA_PATH environment variable so it s value can be restored at the end.
set OLDJAVAPATH=%JAVA_PATH%

rem ### Set the directory of the jdk or jre version desired for this model run
set JAVA_PATH=%JAVA_64_PATH%

rem ### Name the project directory.  This directory will have data and runtime subdirectories
set RUNTIME=%PROJECT_DIRECTORY%
set CONFIG=%RUNTIME%/config


set JAR_LOCATION=%PROJECT_DIRECTORY%/Apps/SDModel
set LIB_JAR_PATH=%JAR_LOCATION%\*

rem ### Define the CLASSPATH environment variable for the classpath needed in this model run.
set OLDCLASSPATH=%CLASSPATH%
set CLASSPATH=%CONFIG%;%RUNTIME%;%LIB_JAR_PATH%;

rem ### Save the name of the PATH environment variable, so it can be restored at the end of the model run.
set OLDPATH=%PATH%

rem ### Change the PATH environment variable so that JAVA_HOME is listed first in the PATH.
rem ### Doing this ensures that the JAVA_HOME path we defined above is the on that gets used in case other java paths are in PATH.
set PATH=%JAVA_PATH%\bin;%OLDPATH%

rem =========================================================================================
rem short-distance resident model
rem SDT Residents
set PROPERTIES_NAME= floridaturnpike
%JAVA_64_PATH%\bin\java -server -Xms%MEMORY_SPMARKET_MIN% -Xmx%MEMORY_SPMARKET_MAX% -cp "%CLASSPATH%" -Djava.library.path=%JAR_LOCATION%  -Djxl.nowarnings=true -Dlog4j.configuration=log4j.xml -Dproject.folder=%PROJECT_DIRECTORY% visitormodel.VisitorModelRunner %PROPERTIES_NAME% -iteration %ITERATION% -sampleRate %SAMPLERATE%  

rem =========================================================================================
rem ### restore saved environment variable values, and change back to original current directory
set JAVA_PATH=%OLDJAVAPATH%
set PATH=%OLDPATH%
set CLASSPATH=%OLDCLASSPATH%
