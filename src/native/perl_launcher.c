#define PERL_NO_GET_CONTEXT
#include "EXTERN.h"
#include "perl.h"

EXTERN_C void boot_DynaLoader(pTHX_ CV *cv);

static void
xs_init(pTHX)
{
    const char *file = __FILE__;
    dXSUB_SYS;
    newXS("DynaLoader::boot_DynaLoader", boot_DynaLoader, file);
}

int
main(int argc, char **argv, char **env)
{
    int status;
    PerlInterpreter *my_perl;

    PERL_SYS_INIT3(&argc, &argv, &env);
    my_perl = perl_alloc();
    if (!my_perl) {
        PERL_SYS_TERM();
        return 1;
    }

    PERL_SET_CONTEXT(my_perl);
    perl_construct(my_perl);
    PL_exit_flags |= PERL_EXIT_DESTRUCT_END;
    status = perl_parse(my_perl, xs_init, argc, argv, NULL);
    if (status == 0) {
        status = perl_run(my_perl);
    }
    perl_destruct(my_perl);
    perl_free(my_perl);
    PERL_SYS_TERM();
    return status;
}

